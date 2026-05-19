"""
Thumbnails Tab - style_thumbnails.json 뷰어
좌측 카테고리 버튼 + 우측 3열 썸네일 그리드
"""
import json
import base64
from pathlib import Path
from typing import Dict, List, Set, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QButtonGroup, QTabWidget, QScrollArea,
    QGridLayout, QSizePolicy, QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap

from interfaces.base_tab_module import BaseTabModule
from legacy_desktop.ui.theme import DARK_COLORS, DARK_STYLES
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size


# ─── 백그라운드 JSON 로더 ─────────────────────────────────────────────

class StyleJsonLoadWorker(QThread):
    """대용량 JSON 파일 로드 워커 스레드"""
    load_finished = pyqtSignal(object, str)  # data, error_message

    def __init__(self, file_path: Path, parent=None):
        super().__init__(parent)
        self.file_path = file_path

    def run(self):
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.load_finished.emit(data, "")
        except Exception as e:
            self.load_finished.emit(None, str(e))


# ─── 썸네일 카드 위젯 ─────────────────────────────────────────────────

class StyleThumbnailCard(QFrame):
    """개별 스타일 썸네일 카드 (Image + Tag Name)"""
    clicked = pyqtSignal(str)

    def __init__(self, tag_name: str, thumbnail_base64: str, parent=None):
        super().__init__(parent)
        self.tag_name = tag_name
        self._pixmap_original: Optional[QPixmap] = None

        self.setFrameStyle(QFrame.Shape.Box)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(6)}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            get_scaled_size(4), get_scaled_size(4),
            get_scaled_size(4), get_scaled_size(4)
        )
        layout.setSpacing(get_scaled_size(4))

        # 이미지 라벨
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(get_scaled_size(120), get_scaled_size(120))
        self.image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.image_label.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
            }}
        """)
        layout.addWidget(self.image_label, stretch=1)

        # 태그 이름 라벨 (클릭 시 복사)
        self.name_label = QLabel(tag_name)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.name_label.setToolTip("클릭하여 복사")
        self._name_default_style = f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(18)}px;
                padding: {get_scaled_size(2)}px;
                border: none;
                background: transparent;
            }}
        """
        self._name_copied_style = f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(18)}px;
                padding: {get_scaled_size(2)}px;
                border: none;
                background: transparent;
            }}
        """
        self.name_label.setStyleSheet(self._name_default_style)
        self.name_label.mousePressEvent = self._copy_tag_name
        layout.addWidget(self.name_label)

        # 썸네일 로드
        self._load_thumbnail(thumbnail_base64)

    def _load_thumbnail(self, base64_data: str):
        if not base64_data:
            self.image_label.setText("No Image")
            return
        try:
            img_bytes = base64.b64decode(base64_data)
            pixmap = QPixmap()
            pixmap.loadFromData(img_bytes)
            if pixmap.isNull():
                self.image_label.setText("No Image")
                return
            self._pixmap_original = pixmap
            self._update_image_display()
        except Exception:
            self.image_label.setText("Error")

    def _update_image_display(self):
        if self._pixmap_original and not self._pixmap_original.isNull():
            scaled = self._pixmap_original.scaled(
                self.image_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)

    def _copy_tag_name(self, event):
        """태그 이름을 클립보드에 복사 + 시각 피드백"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.tag_name)
        self.name_label.setStyleSheet(self._name_copied_style)
        self.name_label.setText(f"✓ {self.tag_name}")
        QTimer.singleShot(1000, self._reset_name_label)

    def _reset_name_label(self):
        self.name_label.setStyleSheet(self._name_default_style)
        self.name_label.setText(self.tag_name)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self.clicked.emit(self.tag_name)


# ─── 리사이즈 감지 ScrollArea ──────────────────────────────────────────

class _ResizeAwareScrollArea(QScrollArea):
    """viewport 리사이즈 시 시그널 발생"""
    viewport_resized = pyqtSignal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.viewport_resized.emit()


# ─── 메인 탭 모듈 ─────────────────────────────────────────────────────

class ThumbnailsTabModule(BaseTabModule):
    """스타일 썸네일 뷰어 탭"""

    THUMBNAILS_PATH = Path("data/taglist/style_thumbnails.json")
    META_TAGS_PATH = Path("data/taglist/style_meta_tags.json")

    def __init__(self):
        super().__init__()
        self.widget = None

        # 데이터
        self.thumbnail_data: Dict[str, str] = {}          # tag -> base64
        self.meta_categories: Dict[str, dict] = {}        # key -> {name, tags}
        self.category_keys: List[str] = []                 # 카테고리 키 순서
        self.category_tags: Dict[str, List[str]] = {}     # key -> [유효 태그]

        # 상태
        self._data_loaded = False
        self._loading = False
        self._populated_categories: Set[str] = set()
        self._current_category: Optional[str] = None

        # 위젯 참조
        self.loading_label: Optional[QLabel] = None
        self.content_widget: Optional[QWidget] = None
        self.category_button_group: Optional[QButtonGroup] = None
        self.category_buttons: Dict[str, QPushButton] = {}
        self.grid_scroll_area: Optional[QScrollArea] = None
        self._card_widgets: Dict[str, StyleThumbnailCard] = {}

        # 리사이즈 디바운스 (컨테이너 레벨에서 1회)
        self._resize_timer: Optional[QTimer] = None

        # 스레드
        self._load_worker: Optional[StyleJsonLoadWorker] = None

    def get_tab_title(self) -> str:
        return "🖼️ Thumb"

    def get_tab_order(self) -> int:
        return 8

    def get_tab_type(self) -> str:
        return 'core'

    # ─── 위젯 생성 ───────────────────────────────────────────────

    def create_widget(self, parent: QWidget) -> QWidget:
        self.widget = QWidget(parent)
        main_layout = QVBoxLayout(self.widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 최상위 탭 ("Meta")
        top_tab_widget = QTabWidget()
        top_tab_widget.setStyleSheet(DARK_STYLES['dark_tabs'])
        main_layout.addWidget(top_tab_widget)

        # Meta 탭 콘텐츠
        meta_widget = self._create_meta_content()
        top_tab_widget.addTab(meta_widget, "Meta")

        return self.widget

    def _create_meta_content(self) -> QWidget:
        """Meta 탭 내부: 좌측 카테고리 버튼 + 우측 썸네일 그리드"""
        meta = QWidget()
        layout = QVBoxLayout(meta)
        layout.setContentsMargins(0, 0, 0, 0)

        # 메타 태그 카테고리 로드
        self._load_meta_tags()

        # 로딩 라벨
        self.loading_label = QLabel("탭을 활성화하면 썸네일을 로드합니다...")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(18)}px;
                padding: {get_scaled_size(40)}px;
            }}
        """)

        # 콘텐츠 영역: 좌측 카테고리 버튼 | 우측 그리드
        self.content_widget = QWidget()
        content_layout = QHBoxLayout(self.content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # 좌측: 카테고리 버튼 패널 (고정 폭)
        categories_panel = self._create_categories_panel()
        categories_panel.setFixedWidth(get_scaled_size(180))
        content_layout.addWidget(categories_panel)

        # 우측: 썸네일 그리드 (QScrollArea)
        self.grid_scroll_area = _ResizeAwareScrollArea()
        self.grid_scroll_area.setWidgetResizable(True)
        self.grid_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.grid_scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {DARK_COLORS['bg_tertiary']};
            }}
        """)
        placeholder = QWidget()
        placeholder.setStyleSheet(f"background-color: {DARK_COLORS['bg_tertiary']};")
        self.grid_scroll_area.setWidget(placeholder)
        content_layout.addWidget(self.grid_scroll_area, 1)

        # 리사이즈 디바운스: viewport 리사이즈 → 50ms 후 전체 카드 일괄 업데이트
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._update_all_card_images)
        self.grid_scroll_area.viewport_resized.connect(
            lambda: self._resize_timer.start(50)
        )

        # 초기: 로딩 라벨 표시, 콘텐츠 숨김
        self.content_widget.setVisible(False)
        layout.addWidget(self.loading_label)
        layout.addWidget(self.content_widget)

        return meta

    def _load_meta_tags(self):
        """style_meta_tags.json에서 카테고리 정보 로드 (동기, 작은 파일)"""
        if not self.META_TAGS_PATH.exists():
            return
        try:
            with open(self.META_TAGS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.meta_categories = data.get("categories", {})
            self.category_keys = list(self.meta_categories.keys())
        except Exception as e:
            print(f"⚠️ style_meta_tags.json 로드 실패: {e}")

    def _create_categories_panel(self) -> QWidget:
        """좌측 카테고리 버튼 패널 (스크롤 가능)"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {DARK_COLORS['bg_secondary']};
            }}
        """)

        panel = QWidget()
        panel.setStyleSheet(f"background-color: {DARK_COLORS['bg_secondary']};")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(
            get_scaled_size(4), get_scaled_size(4),
            get_scaled_size(4), get_scaled_size(4)
        )
        layout.setSpacing(get_scaled_size(4))

        self.category_button_group = QButtonGroup(panel)
        self.category_button_group.setExclusive(True)

        button_style = f"""
            QPushButton {{
                font-size: {get_scaled_font_size(18)}px;
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border: 2px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(5)}px;
                padding: {get_scaled_size(10)}px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border-color: {DARK_COLORS['accent_blue']};
            }}
            QPushButton:checked {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                border-color: {DARK_COLORS['accent_blue']};
                font-weight: bold;
            }}
        """

        for key in self.category_keys:
            cat_info = self.meta_categories[key]
            display_name = cat_info.get("name", key)

            button = QPushButton(display_name)
            button.setCheckable(True)
            button.setStyleSheet(button_style)
            button.clicked.connect(
                lambda checked, k=key: self._on_category_clicked(k)
            )
            self.category_button_group.addButton(button)
            self.category_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch()
        scroll.setWidget(panel)
        return scroll

    # ─── 데이터 로딩 ─────────────────────────────────────────────

    def on_tab_activated(self):
        """탭 활성화 시 최초 1회 데이터 로드"""
        if self._data_loaded or self._loading:
            return
        self._start_loading_thumbnails()

    def _start_loading_thumbnails(self):
        """백그라운드 스레드로 썸네일 JSON 로드"""
        if not self.THUMBNAILS_PATH.exists():
            self.loading_label.setText(
                f"⚠️ 파일 없음: {self.THUMBNAILS_PATH}"
            )
            return

        self._loading = True
        self.loading_label.setText("🔄 썸네일 데이터 로딩 중...")

        self._load_worker = StyleJsonLoadWorker(self.THUMBNAILS_PATH)
        self._load_worker.load_finished.connect(self._on_thumbnails_loaded)
        self._load_worker.finished.connect(self._load_worker.deleteLater)
        self._load_worker.start()

    def _on_thumbnails_loaded(self, data: Optional[dict], error: str):
        """썸네일 JSON 로드 완료"""
        self._loading = False
        self._load_worker = None

        if error or data is None:
            self.loading_label.setText(f"⚠️ 로드 실패: {error}")
            return

        self.thumbnail_data = data
        self._data_loaded = True

        # 카테고리별 유효 태그 (썸네일 있는 것만)
        for key in self.category_keys:
            cat_tags = self.meta_categories[key].get("tags", [])
            valid_tags = [t for t in cat_tags if t in self.thumbnail_data]
            self.category_tags[key] = valid_tags

        # UI 전환
        self.loading_label.setVisible(False)
        self.content_widget.setVisible(True)

        # 첫 번째 카테고리 자동 선택
        if self.category_keys:
            first_key = self.category_keys[0]
            self.category_buttons[first_key].setChecked(True)
            self._on_category_clicked(first_key)

    # ─── 카테고리 전환 ───────────────────────────────────────────

    def _on_category_clicked(self, category_key: str):
        """카테고리 버튼 클릭 → 우측 그리드 갱신"""
        if not self._data_loaded:
            return
        if category_key == self._current_category:
            return

        self._current_category = category_key
        self._populate_category_grid(category_key)

    # ─── 그리드 채우기 ───────────────────────────────────────────

    def _populate_category_grid(self, category_key: str):
        """카테고리의 썸네일 그리드를 우측 scroll area에 표시"""
        self._card_widgets.clear()
        tags = self.category_tags.get(category_key, [])

        content = QWidget()
        content.setStyleSheet(
            f"background-color: {DARK_COLORS['bg_tertiary']};"
        )
        grid = QGridLayout(content)
        grid.setSpacing(get_scaled_size(8))
        grid.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8)
        )

        # 3열 균등 분배
        for col in range(3):
            grid.setColumnStretch(col, 1)

        if not tags:
            empty_label = QLabel("이 카테고리에 썸네일이 없습니다.")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_label.setStyleSheet(
                f"color: {DARK_COLORS['text_secondary']}; "
                f"font-size: {get_scaled_font_size(14)}px; "
                f"padding: {get_scaled_size(40)}px;"
            )
            grid.addWidget(empty_label, 0, 0, 1, 3)
        else:
            for idx, tag_name in enumerate(tags):
                row, col = divmod(idx, 3)
                base64_data = self.thumbnail_data.get(tag_name, "")
                card = StyleThumbnailCard(tag_name, base64_data, content)
                grid.addWidget(card, row, col)
                self._card_widgets[tag_name] = card

        self.grid_scroll_area.setWidget(content)

    # ─── 리사이즈 일괄 업데이트 ──────────────────────────────────

    def _update_all_card_images(self):
        """현재 카테고리의 모든 카드 이미지를 일괄 업데이트"""
        if not self._current_category:
            return
        tags = self.category_tags.get(self._current_category, [])
        for tag_name in tags:
            card = self._card_widgets.get(tag_name)
            if card:
                card._update_image_display()

    # ─── 정리 ────────────────────────────────────────────────────

    def cleanup(self):
        """리소스 정리"""
        if self._load_worker and self._load_worker.isRunning():
            self._load_worker.quit()
            self._load_worker.wait(3000)
