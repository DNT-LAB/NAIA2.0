"""Character Viewer — NAIA 2.0 확장기능.

캐릭터 분석 결과 뷰어. copyright_groups.json + character_analysis.json 데이터를 기반으로
캐릭터별 Personal Color, Characteristics, Alternate Costume 정보를 탐색한다.
"""

import io
import json
import math
import re
from pathlib import Path

from PyQt6.QtCore import Qt, QSortFilterProxyModel, QModelIndex, QTimer, pyqtSignal
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QColor, QFont, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QListView, QTreeWidget, QTreeWidgetItem, QLabel, QLineEdit,
    QSplitter, QHeaderView, QFrame, QTextEdit, QPushButton, QCheckBox,
    QSizePolicy, QTabWidget, QGridLayout, QMessageBox,
)

from ui.theme import DARK_COLORS, DARK_STYLES
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

# ---- 데이터 경로 ----
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
GROUPS_PATH = DATA_DIR / "copyright_groups.json"
ANALYSIS_PATH = DATA_DIR / "character_analysis.json"

# ---- 썸네일 저장 경로 ----
THUMB_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "character_thumbnails"
THUMB_INDEX_PATH = THUMB_DIR / "index.json"
THUMB_MAX_SIZE = (416, 608)

# ---- 태그 저장 경로 ----
SAVE_DIR = Path(__file__).resolve().parent.parent.parent / "save"
TAGS_SAVE_PATH = SAVE_DIR / "character_viewer_tags.json"

# ---- 태그 카테고리 색상 (장식용, 테마 독립) ----
COLOR_PC = "#f5c2e7"      # Personal Color 헤더
COLOR_CH = "#a6e3a1"      # Characteristics 헤더
COLOR_ATTIRE = "#f9e2af"  # Attire / Alternate 헤더

# ---- UI 상수 ----
TAG_SEARCH_ROLE = Qt.ItemDataRole.UserRole + 1

GRID_COLS = 4
GRID_ROWS = 3
GRID_PAGE_SIZE = GRID_COLS * GRID_ROWS  # 12


class TagSearchProxyModel(QSortFilterProxyModel):
    """캐릭터 이름 + Personal Color/Characteristics 태그로 필터링.

    '*' 접두사: 퍼펙트 매칭 (태그 단위 exact match + 캐릭터명 word boundary).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_text = ""
        self._exact = False

    def setFilterText(self, text: str):
        raw = text.strip().lower()
        if raw.startswith("*"):
            self._exact = True
            self._filter_text = raw[1:].strip()
        else:
            self._exact = False
            self._filter_text = raw
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self._filter_text:
            return True
        index = self.sourceModel().index(source_row, 0, source_parent)
        display = self.sourceModel().data(index, Qt.ItemDataRole.DisplayRole) or ""
        tag_str = self.sourceModel().data(index, TAG_SEARCH_ROLE) or ""

        if self._exact:
            # 캐릭터명: word boundary 매칭
            if re.search(r'\b' + re.escape(self._filter_text) + r'\b', display.lower()):
                return True
            # 태그: 쉼표 구분 exact match
            tags = {t.strip().lower() for t in tag_str.split(",")} if tag_str else set()
            return self._filter_text in tags
        else:
            if self._filter_text in display.lower():
                return True
            return self._filter_text in tag_str.lower()


class CharacterViewerWindow(QMainWindow):
    """Character Viewer 확장기능 윈도우."""

    window_closed = pyqtSignal()
    apply_to_main_prompt = pyqtSignal(dict)

    # ---- static: 데이터 확인 ----
    @staticmethod
    def ensure_data_available(parent=None) -> bool:
        """copyright_groups.json, character_analysis.json 존재 확인."""
        if GROUPS_PATH.exists() and ANALYSIS_PATH.exists():
            return True

        QMessageBox.warning(
            parent,
            "Character Viewer 데이터",
            "Character Viewer 데이터가 없습니다.\n"
            f"필요 파일:\n  {GROUPS_PATH}\n  {ANALYSIS_PATH}",
        )
        return False

    # ---- 생성자 ----
    def __init__(self, app_context=None, kr_tags_df=None, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._kr_tags_df = kr_tags_df

        self.setWindowTitle("Character Viewer")
        self.setMinimumSize(get_scaled_size(1680), get_scaled_size(980))
        self.resize(
            get_scaled_size(2100),
            get_scaled_size(1200),
        )

        self._apply_theme()

        # 데이터 로드
        with open(GROUPS_PATH, "r", encoding="utf-8") as f:
            self.groups = json.load(f)
        with open(ANALYSIS_PATH, "r", encoding="utf-8") as f:
            self.analysis = json.load(f)

        # 그리드 상태
        self._grid_chars: list[tuple[str, str, int]] = []
        self._grid_page = 0
        self._current_group_key = None
        self._current_char_name = None
        self._current_char_data = None
        self._alternates_list: list[dict] = []
        self._generating = False
        self._preview_qimage = None

        self._load_thumbnail_index()
        self._build_ui()
        self._load_tags()
        self._populate_groups()

        # [1] 윈도우 진입 시 All 그룹 자동 선택
        if self.group_model.rowCount() > 0:
            first_proxy_idx = self.group_proxy.index(0, 0)
            if first_proxy_idx.isValid():
                self.group_list.setCurrentIndex(first_proxy_idx)

        # [2] 썸네일 우선 정렬: UI/데이터 안정 후 체크 (0.5초 지연)
        QTimer.singleShot(500, lambda: self.grid_thumb_sort_cb.setChecked(True))

        # [3] 자동화 중단 이벤트 구독 (연속 생성 체크 해제)
        if self.app_context:
            self.app_context.subscribe("automation_stopped", self._on_automation_stopped)

    # ---- closeEvent ----
    def closeEvent(self, event):
        self._save_tags()
        self._unsubscribe_generation()
        # 자동화 중단 이벤트 구독 해제
        if self.app_context:
            subs = self.app_context.subscribers.get("automation_stopped")
            if subs and self._on_automation_stopped in subs:
                subs.remove(self._on_automation_stopped)
        self.window_closed.emit()
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_preview_scale()

    def _refresh_preview_scale(self):
        """저장된 QImage를 preview_label 크기에 맞게 재스케일."""
        if not self._preview_qimage or self._preview_qimage.isNull():
            return
        pixmap = QPixmap.fromImage(self._preview_qimage)
        scaled = pixmap.scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

    # ==================================================================
    #  UI 구성
    # ==================================================================

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8),
        )
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        # === Left: copyright groups ===
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, get_scaled_size(4), 0)
        left_layout.setSpacing(get_scaled_size(4))

        self.group_search = QLineEdit()
        self.group_search.setPlaceholderText("Search groups...")
        left_layout.addWidget(self.group_search)

        self.group_model = QStandardItemModel()
        self.group_proxy = QSortFilterProxyModel()
        self.group_proxy.setSourceModel(self.group_model)
        self.group_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.group_list = QListView()
        self.group_list.setModel(self.group_proxy)
        left_layout.addWidget(self.group_list)
        splitter.addWidget(left)

        # === Middle: characters ===
        mid = QWidget()
        mid_layout = QVBoxLayout(mid)
        mid_layout.setContentsMargins(get_scaled_size(4), 0, get_scaled_size(4), 0)
        mid_layout.setSpacing(get_scaled_size(4))

        self.char_search = QLineEdit()
        self.char_search.setPlaceholderText("Search characters or tags...")
        mid_layout.addWidget(self.char_search)

        self.char_model = QStandardItemModel()
        self.char_proxy = TagSearchProxyModel()
        self.char_proxy.setSourceModel(self.char_model)
        self.char_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.char_list = QListView()
        self.char_list.setModel(self.char_proxy)
        mid_layout.addWidget(self.char_list)
        splitter.addWidget(mid)

        # === Right: QTabWidget ===
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(get_scaled_size(4), 0, 0, 0)
        right_layout.setSpacing(0)

        self.right_tabs = QTabWidget()
        right_layout.addWidget(self.right_tabs)

        self._build_grid_tab()
        self._build_detail_tab()

        splitter.addWidget(right)
        splitter.setSizes([
            get_scaled_size(330),
            get_scaled_size(390),
            get_scaled_size(1380),
        ])

        # Connections
        self.group_search.textChanged.connect(self.group_proxy.setFilterFixedString)
        self._char_search_timer = QTimer(self)
        self._char_search_timer.setSingleShot(True)
        self._char_search_timer.setInterval(350)
        self._char_search_timer.timeout.connect(self._on_char_search_apply)
        self.char_search.textChanged.connect(lambda _: self._char_search_timer.start())
        self.group_list.selectionModel().selectionChanged.connect(self._on_group_selected)
        self.group_list.clicked.connect(self._on_group_clicked_always)
        self.char_list.selectionModel().selectionChanged.connect(self._on_char_selected)
        self.right_tabs.currentChanged.connect(self._on_right_tab_changed)

    # ---- Grid Tab ----

    def _build_grid_tab(self):
        grid_page = QWidget()
        grid_outer = QVBoxLayout(grid_page)
        grid_outer.setContentsMargins(
            get_scaled_size(2), get_scaled_size(2),
            get_scaled_size(2), get_scaled_size(2),
        )
        grid_outer.setSpacing(get_scaled_size(2))

        self.grid_container = QWidget()
        self.grid_container.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(get_scaled_size(4))
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        for c in range(GRID_COLS):
            self.grid_layout.setColumnStretch(c, 1)
        for r in range(GRID_ROWS):
            self.grid_layout.setRowStretch(r, 1)
        grid_outer.addWidget(self.grid_container, stretch=1)

        # 하단 바: 체크박스 + 페이지 네비게이션
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(get_scaled_size(8))

        self.grid_thumb_sort_cb = QCheckBox("썸네일 우선 정렬")
        self.grid_thumb_sort_cb.setStyleSheet(DARK_STYLES['dark_checkbox'])
        self.grid_thumb_sort_cb.stateChanged.connect(self._on_thumb_sort_changed)
        nav_layout.addWidget(self.grid_thumb_sort_cb)

        nav_layout.addStretch()

        self.grid_prev_btn = QPushButton("<")
        self.grid_prev_btn.setFixedWidth(get_scaled_size(48))
        self.grid_prev_btn.clicked.connect(self._grid_prev_page)
        nav_layout.addWidget(self.grid_prev_btn)

        self.grid_page_label = QLabel("Page 0 / 0")
        self.grid_page_label.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']}; "
            f"font-size: {get_scaled_font_size(15)}px;"
        )
        nav_layout.addWidget(self.grid_page_label)

        self.grid_next_btn = QPushButton(">")
        self.grid_next_btn.setFixedWidth(get_scaled_size(48))
        self.grid_next_btn.clicked.connect(self._grid_next_page)
        nav_layout.addWidget(self.grid_next_btn)

        nav_layout.addStretch()
        grid_outer.addLayout(nav_layout)

        self.right_tabs.addTab(grid_page, "Characters")

    # ---- Detail Tab ----

    def _build_detail_tab(self):
        detail_page = QWidget()
        detail_layout = QVBoxLayout(detail_page)
        detail_layout.setContentsMargins(
            get_scaled_size(4), get_scaled_size(4),
            get_scaled_size(4), get_scaled_size(4),
        )
        detail_layout.setSpacing(get_scaled_size(6))

        # Vertical splitter: (data + preview) / (prompt area)
        self.right_vsplit = QSplitter(Qt.Orientation.Vertical)
        detail_layout.addWidget(self.right_vsplit)

        # --- Top: data + preview (horizontal) ---
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(get_scaled_size(6))

        # Data panel: Alternate + PC + CH + Attire
        data_panel = QWidget()
        data_layout = QVBoxLayout(data_panel)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.setSpacing(get_scaled_size(4))

        # Alternate tree (hidden by default)
        self.alt_tree = self._make_tree()
        self.alt_tree.setVisible(False)
        self.alt_tree.itemClicked.connect(self._on_alt_tree_clicked)
        data_layout.addWidget(self.alt_tree, stretch=1)

        # Personal Color tree
        self.pc_tree = self._make_tree()
        data_layout.addWidget(self.pc_tree, stretch=1)

        # Characteristics tree
        self.ch_tree = self._make_tree()
        data_layout.addWidget(self.ch_tree, stretch=1)

        # Attire tree (hidden by default, shown on variant select)
        self.attire_tree = self._make_tree()
        self.attire_tree.setVisible(False)
        data_layout.addWidget(self.attire_tree, stretch=1)

        top_layout.addWidget(data_panel, stretch=1)

        # Preview panel: image placeholder (1:1 비율)
        self.preview_frame = QFrame()
        preview_inner = QVBoxLayout(self.preview_frame)
        preview_inner.setContentsMargins(0, 0, 0, 0)
        self.preview_label = QLabel("Preview")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            f"color: {DARK_COLORS['text_secondary']}; "
            f"font-size: {get_scaled_font_size(18)}px;"
        )
        preview_inner.addWidget(self.preview_label)
        top_layout.addWidget(self.preview_frame, stretch=1)

        self.right_vsplit.addWidget(top_widget)

        # --- Bottom: prompt area ---
        prompt_widget = QWidget()
        prompt_layout = QVBoxLayout(prompt_widget)
        prompt_layout.setContentsMargins(0, 0, 0, 0)
        prompt_layout.setSpacing(get_scaled_size(4))

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setAcceptRichText(False)
        self.prompt_edit.setReadOnly(True)
        self.prompt_edit.setPlaceholderText("Character prompt (auto-generated)")
        self.prompt_edit.setMaximumHeight(get_scaled_size(120))
        self.prompt_edit.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']}; "
            f"background-color: {DARK_COLORS['bg_primary']};"
        )
        prompt_layout.addWidget(self.prompt_edit, stretch=3)

        prefix_row = QHBoxLayout()
        prefix_row.setSpacing(get_scaled_size(6))
        prefix_label = QLabel("선행 고정 프롬프트:")
        prefix_label.setFixedWidth(get_scaled_size(150))
        prefix_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        prefix_row.addWidget(prefix_label)
        self.prefix_edit = QTextEdit()
        self.prefix_edit.setAcceptRichText(False)
        self.prefix_edit.setPlaceholderText("Prefix Tags (1girl, artist tags, pose)")
        self.prefix_edit.setMaximumHeight(get_scaled_size(66))
        self.prefix_edit.setStyleSheet(f"color: {DARK_COLORS['text_secondary']};")

        prefix_row.addWidget(self.prefix_edit)
        prompt_layout.addLayout(prefix_row, stretch=1)

        postfix_row = QHBoxLayout()
        postfix_row.setSpacing(get_scaled_size(6))
        postfix_label = QLabel("후행 고정 프롬프트:")
        postfix_label.setFixedWidth(get_scaled_size(150))
        postfix_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        postfix_row.addWidget(postfix_label)
        self.postfix_edit = QTextEdit()
        self.postfix_edit.setAcceptRichText(False)
        self.postfix_edit.setPlaceholderText("Postfix Tags (Quality Tags)")
        self.postfix_edit.setMaximumHeight(get_scaled_size(66))
        self.postfix_edit.setStyleSheet(f"color: {DARK_COLORS['text_secondary']};")

        postfix_row.addWidget(self.postfix_edit)
        prompt_layout.addLayout(postfix_row, stretch=1)

        # Controls
        ctrl_layout = QHBoxLayout()
        ctrl_layout.setSpacing(get_scaled_size(8))

        self.group_btn = QPushButton("Group: —")
        self.group_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; "
            f"color: {DARK_COLORS['accent_blue_light']}; "
            f"font-size: {get_scaled_font_size(15)}px; font-weight: normal; "
            f"padding: {get_scaled_size(3)}px {get_scaled_size(10)}px; "
            f"border: 1px solid {DARK_COLORS['border']}; border-radius: 3px; }}"
            f"QPushButton:hover {{ background-color: {DARK_COLORS['bg_hover']}; }}"
        )
        self.group_btn.setVisible(False)
        self.group_btn.clicked.connect(self._on_group_btn_clicked)
        ctrl_layout.addWidget(self.group_btn)

        self.auto_copyright_cb = QCheckBox("copyright 자동 추가")
        self.auto_copyright_cb.setChecked(False)
        ctrl_layout.addWidget(self.auto_copyright_cb)

        self.auto_characteristics_cb = QCheckBox("characteristics 자동 추가")
        self.auto_characteristics_cb.setChecked(True)
        ctrl_layout.addWidget(self.auto_characteristics_cb)

        ctrl_layout.addStretch()

        gen_opts_frame = QFrame()
        gen_opts_frame.setStyleSheet(
            f"QFrame {{ border: 1px solid {DARK_COLORS['border']}; "
            f"border-radius: {get_scaled_size(4)}px; "
            f"padding: {get_scaled_size(2)}px; }}"
        )
        gen_opts_layout = QHBoxLayout(gen_opts_frame)
        gen_opts_layout.setContentsMargins(
            get_scaled_size(6), get_scaled_size(2),
            get_scaled_size(6), get_scaled_size(2),
        )
        gen_opts_layout.setSpacing(get_scaled_size(8))

        self.continuous_gen_cb = QCheckBox("연속 생성")
        gen_opts_layout.addWidget(self.continuous_gen_cb)

        self.empty_thumb_only_cb = QCheckBox("빈 썸네일만")
        self.empty_thumb_only_cb.setChecked(True)
        gen_opts_layout.addWidget(self.empty_thumb_only_cb)

        ctrl_layout.addWidget(gen_opts_frame)

        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setFixedWidth(get_scaled_size(80))
        self.copy_btn.clicked.connect(self._on_copy_prompt)
        ctrl_layout.addWidget(self.copy_btn)

        self.send_btn = QPushButton("Send to Main")
        self.send_btn.setFixedWidth(get_scaled_size(160))
        self.send_btn.clicked.connect(self._on_send_to_main)
        ctrl_layout.addWidget(self.send_btn)

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setFixedWidth(get_scaled_size(160))
        self.generate_btn.clicked.connect(self._on_generate_clicked)
        ctrl_layout.addWidget(self.generate_btn)

        prompt_layout.addLayout(ctrl_layout)

        self.right_vsplit.addWidget(prompt_widget)
        self.right_vsplit.setSizes([get_scaled_size(800), get_scaled_size(280)])

        self.right_tabs.addTab(detail_page, "Detail")

    def _make_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabels(["Tag", "Count", "%"])
        tree.setRootIsDecorated(True)
        tree.setIndentation(get_scaled_size(16))
        tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        return tree

    # ==================================================================
    #  Theme
    # ==================================================================

    def _apply_theme(self) -> None:
        """NAIA 다크 테마 적용 (parent=None 독립 윈도우용)."""
        fs = get_scaled_font_size
        ss = get_scaled_size

        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QToolTip {{
                background-color: #2B2B2B;
                color: #FFFFFF;
                border: 1px solid #555555;
                font-size: {fs(16)}px;
                padding: {ss(4)}px {ss(6)}px;
            }}
            QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                font-size: {fs(18)}px;
            }}
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                border: none;
                font-size: {fs(18)}px;
            }}
            QLineEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {ss(3)}px;
                padding: {ss(5)}px {ss(10)}px;
                font-size: {fs(18)}px;
            }}
            QListView {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                font-size: {fs(18)}px;
            }}
            QListView::item {{
                padding: {ss(4)}px {ss(6)}px;
            }}
            QListView::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
            }}
            QListView::item:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QListView::item:hover:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
            }}
            QTreeWidget {{
                background-color: #212121;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                font-size: {fs(18)}px;
            }}
            QTreeWidget::item {{
                padding: {ss(3)}px 0px;
            }}
            QTreeWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
            }}
            QTreeWidget::item:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QTreeWidget::item:hover:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
            }}
            QHeaderView::section {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                padding: {ss(5)}px;
                font-size: {fs(15)}px;
            }}
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {ss(3)}px;
                padding: {ss(8)}px;
                font-size: {fs(18)}px;
            }}
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {ss(4)}px;
                padding: {ss(7)}px {ss(14)}px;
                font-size: {fs(17)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
            }}
            QTabWidget::pane {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-top: none;
            }}
            QTabBar::tab {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-bottom: none;
                padding: {ss(7)}px {ss(18)}px;
                font-size: {fs(17)}px;
            }}
            QTabBar::tab:selected {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QSplitter::handle:horizontal {{
                background-color: {DARK_COLORS['border']};
                width: 1px;
            }}
            QSplitter::handle:vertical {{
                background-color: {DARK_COLORS['border']};
                height: 1px;
            }}
            QFrame {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
            QCheckBox {{
                color: {DARK_COLORS['text_primary']};
                font-size: {fs(16)}px;
                spacing: {ss(6)}px;
            }}
            QCheckBox::indicator {{
                width: {ss(18)}px;
                height: {ss(18)}px;
            }}
            QScrollBar:vertical {{
                background-color: {DARK_COLORS['bg_primary']};
                width: {ss(10)}px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background-color: {DARK_COLORS['border']};
                min-height: {ss(30)}px;
                border-radius: {ss(5)}px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar:horizontal {{
                background-color: {DARK_COLORS['bg_primary']};
                height: {ss(10)}px;
                border: none;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {DARK_COLORS['border']};
                min-width: {ss(30)}px;
                border-radius: {ss(5)}px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
        """)

    # ==================================================================
    #  Grid Tab
    # ==================================================================

    def _on_char_search_apply(self):
        """검색어 입력 지연 후 적용 → 캐릭터 리스트 필터 + 그리드 동기화."""
        self.char_proxy.setFilterText(self.char_search.text())
        # [2] 검색 시 캐릭터 리스트 선택 해제 (검색 결과에 의한 자동 선택 방지)
        self.char_list.clearSelection()
        self._sync_grid_with_proxy()

    def _sync_grid_with_proxy(self):
        """char_proxy의 필터링 결과로 그리드를 갱신."""
        self._grid_chars = []
        for row in range(self.char_proxy.rowCount()):
            source_idx = self.char_proxy.mapToSource(self.char_proxy.index(row, 0))
            item = self.char_model.itemFromIndex(source_idx)
            gk, name = item.data(Qt.ItemDataRole.UserRole)
            data = self.analysis.get(gk, {}).get(name, {})
            if data:
                self._grid_chars.append((gk, name, data["total_rows"]))
        self._apply_thumb_sort()
        self._grid_page = 0
        self._render_grid_page()

    def _populate_grid(self, group_key):
        """그룹 변경 시 그리드 재구성 (검색어 활성 시 필터 적용)."""
        if group_key == "__ALL__":
            all_chars = self._get_all_chars()
            self._grid_chars = [
                (gk, name, data["total_rows"]) for gk, name, data in all_chars
            ]
        else:
            chars_data = self.analysis.get(group_key, {})
            sorted_chars = sorted(chars_data.items(), key=lambda x: -x[1]["total_rows"])
            self._grid_chars = [
                (group_key, name, data["total_rows"]) for name, data in sorted_chars
            ]
        # 검색어가 있으면 proxy 필터로 동기화
        if self.char_search.text().strip():
            self._sync_grid_with_proxy()
        else:
            self._apply_thumb_sort()
            self._grid_page = 0
            self._render_grid_page()

    def _on_thumb_sort_changed(self):
        """썸네일 우선 정렬 체크박스 변경 시 재정렬."""
        self._apply_thumb_sort()
        self._grid_page = 0
        self._render_grid_page()

    def _apply_thumb_sort(self):
        """체크 시 썸네일 있는 캐릭터를 앞으로, 해제 시 원래 순서(total_rows 내림차순) 복원."""
        if self.grid_thumb_sort_cb.isChecked():
            self._grid_chars.sort(
                key=lambda item: (f"{item[0]}::{item[1]}" not in self._thumb_index, -item[2])
            )
        else:
            self._grid_chars.sort(key=lambda item: -item[2])

    def _grid_total_pages(self):
        if not self._grid_chars:
            return 1
        return math.ceil(len(self._grid_chars) / GRID_PAGE_SIZE)

    def _grid_prev_page(self):
        if self._grid_page > 0:
            self._grid_page -= 1
            self._render_grid_page()

    def _grid_next_page(self):
        if self._grid_page < self._grid_total_pages() - 1:
            self._grid_page += 1
            self._render_grid_page()

    def _render_grid_page(self):
        # 기존 셀 제거
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        total_pages = self._grid_total_pages()
        self.grid_page_label.setText(f"Page {self._grid_page + 1} / {total_pages}")
        self.grid_prev_btn.setEnabled(self._grid_page > 0)
        self.grid_next_btn.setEnabled(self._grid_page < total_pages - 1)

        start = self._grid_page * GRID_PAGE_SIZE
        end = start + GRID_PAGE_SIZE
        page_chars = self._grid_chars[start:end]

        # 셀 크기 계산 (Ignored 정책으로 컨테이너 크기가 안정적)
        container_w = self.grid_container.width()
        container_h = self.grid_container.height()

        if container_w < 10 or container_h < 10:
            QTimer.singleShot(0, self._render_grid_page)
            return

        spacing = get_scaled_size(4)
        cell_margin = get_scaled_size(2)
        cell_spacing = get_scaled_size(2)
        btn_h = get_scaled_size(28)

        cell_w = (container_w - spacing * (GRID_COLS - 1)) // GRID_COLS
        cell_h = (container_h - spacing * (GRID_ROWS - 1)) // GRID_ROWS
        inner_w = cell_w - cell_margin * 2
        thumb_h = max(cell_h - cell_margin * 2 - cell_spacing - btn_h, get_scaled_size(60))

        for i, (gk, name, total_rows) in enumerate(page_chars):
            row = i // GRID_COLS
            col = i % GRID_COLS

            cell = QFrame()
            cell.setFixedSize(cell_w, cell_h)
            cell.setStyleSheet(
                f"QFrame {{ background-color: {DARK_COLORS['bg_secondary']}; "
                f"border: 1px solid {DARK_COLORS['border']}; border-radius: 4px; }}"
            )
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(cell_margin, cell_margin, cell_margin, cell_margin)
            cell_layout.setSpacing(cell_spacing)

            # 썸네일 (cover 모드: 셀을 꽉 채우고 상단 기준 크롭)
            thumb = QLabel()
            thumb.setFixedSize(inner_w, thumb_h)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setStyleSheet(
                f"background-color: {DARK_COLORS['border']}; border-radius: 4px; "
                f"color: {DARK_COLORS['text_secondary']}; "
                f"font-size: {get_scaled_font_size(14)}px; border: none;"
            )
            thumb_key = f"{gk}::{name}"
            thumb_file = self._thumb_index.get(thumb_key)
            thumb_path = THUMB_DIR / thumb_file if thumb_file else None
            if thumb_path and thumb_path.exists():
                pix = QPixmap.fromImage(QImage(str(thumb_path)))
                scaled = pix.scaled(
                    inner_w, thumb_h,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                if scaled.width() > inner_w or scaled.height() > thumb_h:
                    x = (scaled.width() - inner_w) // 2
                    y = (scaled.height() - thumb_h) // 3
                    thumb.setPixmap(scaled.copy(x, y, inner_w, thumb_h))
                else:
                    thumb.setPixmap(scaled)
            else:
                placeholder = QPixmap(inner_w, thumb_h)
                placeholder.fill(QColor(DARK_COLORS['border']))
                painter = QPainter(placeholder)
                painter.setPen(QColor(DARK_COLORS['text_secondary']))
                painter.setFont(QFont("", get_scaled_font_size(14)))
                painter.drawText(placeholder.rect(), Qt.AlignmentFlag.AlignCenter, "No Image")
                painter.end()
                thumb.setPixmap(placeholder)
            cell_layout.addWidget(thumb)

            # 캐릭터 이름 버튼
            btn = QPushButton(name)
            btn.setToolTip(f"{name} ({total_rows:,} rows)")
            btn.setFixedHeight(btn_h)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; "
                f"color: {DARK_COLORS['text_primary']}; "
                f"font-size: {get_scaled_font_size(15)}px; font-weight: normal; "
                f"padding: {get_scaled_size(3)}px {get_scaled_size(6)}px; "
                f"border: none; text-align: center; }}"
                f"QPushButton:hover {{ color: {DARK_COLORS['accent_blue_light']}; }}"
            )
            btn.clicked.connect(
                lambda checked, g=gk, n=name: self._on_grid_char_clicked(g, n)
            )
            cell_layout.addWidget(btn)

            self.grid_layout.addWidget(cell, row, col)

    def _on_grid_char_clicked(self, group_key, char_name):
        """그리드 클릭 → 캐릭터 리스트에서 해당 항목 선택 (일관성)."""
        for row in range(self.char_model.rowCount()):
            item = self.char_model.item(row)
            gk, name = item.data(Qt.ItemDataRole.UserRole)
            if gk == group_key and name == char_name:
                proxy_idx = self.char_proxy.mapFromSource(item.index())
                if proxy_idx.isValid():
                    current = self.char_list.currentIndex()
                    if current == proxy_idx:
                        # 이미 선택된 항목 → selectionChanged 미발동이므로 직접 처리
                        data = self.analysis.get(gk, {}).get(name, {})
                        if data:
                            self._show_char_detail(gk, name, data)
                            self.right_tabs.setCurrentIndex(1)
                    else:
                        self.char_list.setCurrentIndex(proxy_idx)
                return

    # ==================================================================
    #  Data Population
    # ==================================================================

    def _populate_groups(self):
        group_keys = [k for k in self.groups if not k.startswith("_")]
        group_info = []
        all_total = 0
        for gk in group_keys:
            n_girls = len(self.groups[gk].get("girl", []))
            n_boys = len(self.groups[gk].get("boy", []))
            total = n_girls + n_boys
            all_total += total
            group_info.append((gk, total))
        group_info.sort(key=lambda x: -x[1])

        all_item = QStandardItem(f"All  ({all_total})")
        all_item.setData("__ALL__", Qt.ItemDataRole.UserRole)
        all_item.setEditable(False)
        self.group_model.appendRow(all_item)

        for gk, total in group_info:
            item = QStandardItem(f"{gk}  ({total})")
            item.setData(gk, Qt.ItemDataRole.UserRole)
            item.setEditable(False)
            self.group_model.appendRow(item)

    @staticmethod
    def _build_tag_search_str(data) -> str:
        parts = []
        for e in data.get("personal_color", []):
            parts.append(e["tag"])
        for e in data.get("characteristics", []):
            parts.append(e["tag"])
        # breast_size: 가장 빈도 높은 대표 태그만 포함 (전체 분포 포함 시 false match 발생)
        bs = data.get("breast_size", {})
        dist = bs.get("distribution", [])
        if dist:
            top = max(dist, key=lambda e: e.get("count", 0))
            parts.append(top["tag"])
        return ", ".join(parts)

    def _get_all_chars(self):
        all_chars = []
        for gk, chars_data in self.analysis.items():
            for name, data in chars_data.items():
                all_chars.append((gk, name, data))
        all_chars.sort(key=lambda x: -x[2]["total_rows"])
        return all_chars

    # ==================================================================
    #  Selection / Navigation
    # ==================================================================

    def _on_right_tab_changed(self, index):
        """Characters 탭 전환 시 그리드 갱신 (페이지 유지)."""
        if index == 0:
            self._render_grid_page()

    def _on_group_clicked_always(self, _index):
        """이미 선택된 그룹 재클릭 시에도 Characters 탭으로 전환."""
        self.right_tabs.setCurrentIndex(0)

    def _on_group_selected(self, selected, _deselected):
        indexes = selected.indexes()
        if not indexes:
            return
        source_idx = self.group_proxy.mapToSource(indexes[0])
        gk = self.group_model.itemFromIndex(source_idx).data(Qt.ItemDataRole.UserRole)

        self.char_model.clear()
        self.char_search.clear()

        if gk == "__ALL__":
            all_chars = self._get_all_chars()
            for group_key, name, data in all_chars:
                item = QStandardItem(f"{name}  ({data['total_rows']:,})")
                item.setData((group_key, name), Qt.ItemDataRole.UserRole)
                item.setData(self._build_tag_search_str(data), TAG_SEARCH_ROLE)
                item.setEditable(False)
                self.char_model.appendRow(item)
        else:
            chars_data = self.analysis.get(gk, {})
            sorted_chars = sorted(chars_data.items(), key=lambda x: -x[1]["total_rows"])
            for name, data in sorted_chars:
                item = QStandardItem(f"{name}  ({data['total_rows']:,})")
                item.setData((gk, name), Qt.ItemDataRole.UserRole)
                item.setData(self._build_tag_search_str(data), TAG_SEARCH_ROLE)
                item.setEditable(False)
                self.char_model.appendRow(item)

        self.pc_tree.clear()
        self.ch_tree.clear()
        self._update_prompt()

        self._populate_grid(gk)
        self.right_tabs.setCurrentIndex(0)

    def _on_char_selected(self, selected, _deselected):
        indexes = selected.indexes()
        if not indexes:
            return
        source_idx = self.char_proxy.mapToSource(indexes[0])
        item = self.char_model.itemFromIndex(source_idx)
        gk, name = item.data(Qt.ItemDataRole.UserRole)

        data = self.analysis.get(gk, {}).get(name, {})
        if not data:
            return

        self._show_char_detail(gk, name, data)
        self.right_tabs.setCurrentIndex(1)

    def _on_group_btn_clicked(self):
        gk = self._current_group_key
        if not gk:
            return
        for row in range(self.group_model.rowCount()):
            item = self.group_model.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == gk:
                proxy_idx = self.group_proxy.mapFromSource(item.index())
                if proxy_idx.isValid():
                    self.group_list.setCurrentIndex(proxy_idx)
                break

    # ==================================================================
    #  Detail View
    # ==================================================================

    def _show_char_detail(self, group_key, char_name, data):
        self._current_group_key = group_key
        self._current_char_name = char_name
        self._current_char_data = data
        self.group_btn.setText(f"Group: {group_key}")
        self.group_btn.setVisible(True)

        alternates = data.get("alternates", [])
        self._setup_alternate_buttons(alternates)
        self._show_variant_view(None)
        self._load_thumbnail_for_char(group_key, char_name)

    def _setup_alternate_buttons(self, alternates):
        self.alt_tree.clear()
        self._alternates_list = alternates

        if not alternates:
            self.alt_tree.setVisible(False)
            return

        self.alt_tree.setVisible(True)
        parent = QTreeWidgetItem(
            self.alt_tree, [f"Alternate ({len(alternates) + 1})", "", ""]
        )
        parent.setExpanded(True)
        font = parent.font(0)
        font.setBold(True)
        parent.setFont(0, font)
        parent.setForeground(0, QColor(COLOR_ATTIRE))

        default_item = QTreeWidgetItem(parent, ["Default", "", ""])
        default_item.setData(0, Qt.ItemDataRole.UserRole, None)
        default_item.setForeground(0, QColor(DARK_COLORS['accent_blue_light']))
        font_sel = default_item.font(0)
        font_sel.setBold(True)
        default_item.setFont(0, font_sel)

        for variant in alternates:
            label = variant["label"]
            rows_count = variant["rows"]
            vi = QTreeWidgetItem(parent, [label, f"{rows_count}", ""])
            vi.setData(0, Qt.ItemDataRole.UserRole, variant)

    def _on_alt_tree_clicked(self, item, column):
        variant = item.data(0, Qt.ItemDataRole.UserRole)
        if variant is None and item.parent() is None:
            return  # 루트 클릭 무시

        root = self.alt_tree.topLevelItem(0)
        if root:
            for i in range(root.childCount()):
                child = root.child(i)
                f = child.font(0)
                if child is item:
                    f.setBold(True)
                    child.setFont(0, f)
                    child.setForeground(0, QColor(DARK_COLORS['accent_blue_light']))
                else:
                    f.setBold(False)
                    child.setFont(0, f)
                    child.setForeground(0, QColor(DARK_COLORS['text_primary']))

        self._show_variant_view(variant)

    def _show_variant_view(self, variant):
        data = self._current_char_data

        if variant is None:
            pc_items = data.get("personal_color", [])
            ch_items = list(data.get("characteristics", []))
            attire_items = []
            bs = data.get("breast_size", {})
            bs_dist = bs.get("distribution", [])
            if bs_dist:
                top = max(bs_dist, key=lambda x: x["pct"])
                ch_items.insert(0, top)
        else:
            pc_items = variant.get("personal_color", [])
            ch_items = variant.get("characteristics", [])
            attire_items = variant.get("attire", [])

        # Personal Color tree
        self.pc_tree.clear()
        pc_parent = QTreeWidgetItem(
            self.pc_tree, [f"Personal Color ({len(pc_items)})", "", ""]
        )
        pc_parent.setExpanded(True)
        font = pc_parent.font(0)
        font.setBold(True)
        pc_parent.setFont(0, font)
        pc_parent.setForeground(0, QColor(COLOR_PC))
        for entry in pc_items:
            child = QTreeWidgetItem(pc_parent, [
                entry["tag"], f"{entry['count']:,}", f"{entry['pct']}%",
            ])
            alpha = max(0.4, min(1.0, entry["pct"] / 80))
            r, g, b = 205, 214, 244
            child.setForeground(
                0, QColor(int(r * alpha), int(g * alpha), int(b * alpha))
            )
            child.setForeground(2, QColor(COLOR_PC))

        # Characteristics tree
        self.ch_tree.clear()
        ch_parent = QTreeWidgetItem(
            self.ch_tree, [f"Characteristics ({len(ch_items)})", "", ""]
        )
        ch_parent.setExpanded(True)
        font = ch_parent.font(0)
        font.setBold(True)
        ch_parent.setFont(0, font)
        ch_parent.setForeground(0, QColor(COLOR_CH))
        for entry in ch_items:
            child = QTreeWidgetItem(ch_parent, [
                entry["tag"], f"{entry['count']:,}", f"{entry['pct']}%",
            ])
            alpha = max(0.4, min(1.0, entry["pct"] / 80))
            r, g, b = 205, 214, 244
            child.setForeground(
                0, QColor(int(r * alpha), int(g * alpha), int(b * alpha))
            )
            child.setForeground(2, QColor(COLOR_CH))

        # Attire tree (variant only, >= 60%)
        self.attire_tree.clear()
        filtered_attire = [e for e in attire_items if e["pct"] >= 60.0]
        if filtered_attire:
            self.attire_tree.setVisible(True)
            att_parent = QTreeWidgetItem(
                self.attire_tree, [f"Attire ({len(filtered_attire)})", "", ""]
            )
            att_parent.setExpanded(True)
            font = att_parent.font(0)
            font.setBold(True)
            att_parent.setFont(0, font)
            att_parent.setForeground(0, QColor(COLOR_ATTIRE))
            for entry in filtered_attire:
                child = QTreeWidgetItem(att_parent, [
                    entry["tag"], f"{entry['count']:,}", f"{entry['pct']}%",
                ])
                alpha = max(0.4, min(1.0, entry["pct"] / 80))
                r, g, b = 205, 214, 244
                child.setForeground(
                    0, QColor(int(r * alpha), int(g * alpha), int(b * alpha))
                )
                child.setForeground(2, QColor(COLOR_ATTIRE))
            self.right_vsplit.setSizes([get_scaled_size(900), get_scaled_size(180)])
        else:
            self.attire_tree.setVisible(False)
            self.right_vsplit.setSizes([get_scaled_size(800), get_scaled_size(280)])

        variant_label = variant.get("label", "").replace("_", " ") if variant else None
        self._update_prompt(data, ch_items, filtered_attire, variant_label)

    # ==================================================================
    #  Prompt
    # ==================================================================

    def _update_prompt(self, data=None, ch_items=None, attire_items=None, variant_label=None):
        if data is None:
            self.prompt_edit.clear()
            return
        is_nai = self.app_context and self.app_context.get_api_mode() == "NAI"
        char_name = getattr(self, "_current_char_name", "")
        if variant_label:
            char_name = f"{char_name} ({variant_label})"
        # non-NAI: 캐릭터 이름의 괄호 이스케이프
        if not is_nai and char_name:
            char_name = char_name.replace("(", r"\(").replace(")", r"\)")
        # 프롬프트에 큰 영향을 주는 태그 치환/제거
        _TAG_REPLACE = {"loli": "young female"}
        _TAG_EXCLUDE = {"mature female"}

        tags = []
        for entry in data.get("personal_color", []):
            tag = entry["tag"]
            if tag in _TAG_EXCLUDE:
                continue
            tags.append(_TAG_REPLACE.get(tag, tag))
        if self.auto_characteristics_cb.isChecked():
            for entry in (ch_items or data.get("characteristics", [])):
                tag = entry["tag"]
                if tag in _TAG_EXCLUDE:
                    continue
                tags.append(_TAG_REPLACE.get(tag, tag))
        for entry in (attire_items or []):
            tag = entry["tag"]
            if tag in _TAG_EXCLUDE:
                continue
            tags.append(_TAG_REPLACE.get(tag, tag))
        # prefix 구성: girl, {캐릭터}, {copyright(옵션)},
        prefix_parts = []
        if char_name:
            prefix_parts.append("girl")
            prefix_parts.append(char_name)
            if self.auto_copyright_cb.isChecked() and self._current_group_key:
                copyright_tag = self._current_group_key
                if not is_nai:
                    copyright_tag = copyright_tag.replace("(", r"\(").replace(")", r"\)")
                prefix_parts.append(copyright_tag)
        prefix = ", ".join(prefix_parts) + ", " if prefix_parts else ""
        self.prompt_edit.setPlainText(prefix + ", ".join(tags))

    # ==================================================================
    #  Send / Generate
    # ==================================================================

    def _build_tags_dict(self) -> dict:
        """현재 프롬프트의 태그를 dict 형태로 구성 (general 키 사용)."""
        parts = []
        prefix = self.prefix_edit.toPlainText().strip()
        prompt = self.prompt_edit.toPlainText().strip()
        postfix = self.postfix_edit.toPlainText().strip()
        if prefix:
            parts.append(prefix)
        if prompt:
            parts.append(prompt)
        if postfix:
            parts.append(postfix)
        return {"general": ", ".join(parts)}

    def _on_copy_prompt(self):
        """Copy 버튼 → prompt 텍스트를 클립보드에 복사."""
        from PyQt6.QtWidgets import QApplication
        text = self.prompt_edit.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)

    def _on_send_to_main(self):
        """Send to Main 버튼 → 메인 프롬프트 업데이트만 (생성 없음)."""
        tags_dict = self._build_tags_dict()
        if tags_dict.get("general"):
            self.apply_to_main_prompt.emit(tags_dict)

    def _on_generate_clicked(self):
        """Generate 버튼 → overrides로 프롬프트 직접 주입 (메인 프롬프트 미변경)."""
        char_prompt = self.prompt_edit.toPlainText().strip()
        prefix_text = self.prefix_edit.toPlainText().strip()
        postfix_text = self.postfix_edit.toPlainText().strip()
        if not char_prompt and not prefix_text and not postfix_text:
            return
        if self._generating:
            return

        self._save_tags()
        self._set_generating_state(True)

        is_nai = self.app_context and self.app_context.get_api_mode() == "NAI"

        if is_nai:
            # NAI: prefix + postfix → base_caption, 캐릭터 → char_captions 분리
            base_parts = [p for p in (prefix_text, postfix_text) if p]
            cv_overrides = {
                "character_viewer_request": True,
                "input": ", ".join(base_parts),
                "width": 896,
                "height": 1152,
                "random_resolution": False,
            }
            if char_prompt:
                cv_overrides["characters"] = [char_prompt]
                cv_overrides["uc"] = [""]
        else:
            # WEBUI/COMFYUI: char_prompt에서 "girl" 제거 후 prefix의 girl 태그 뒤에 삽입
            char_tags = [t.strip() for t in char_prompt.split(",") if t.strip()] if char_prompt else []
            char_tags = [t for t in char_tags if t.lower() != "girl"]

            prefix_tags = [t.strip() for t in prefix_text.split(",") if t.strip()] if prefix_text else []
            postfix_tags = [t.strip() for t in postfix_text.split(",") if t.strip()] if postfix_text else []

            # prefix에서 "girl"을 포함하는 첫 번째 태그 뒤에 캐릭터 태그 삽입
            insert_idx = 0  # fallback: prefix 맨 앞
            for i, tag in enumerate(prefix_tags):
                if "girl" in tag.lower():
                    insert_idx = i + 1
                    break
            merged = prefix_tags[:insert_idx] + char_tags + prefix_tags[insert_idx:] + postfix_tags

            cv_overrides = {
                "character_viewer_request": True,
                "input": ", ".join(merged),
                "width": 896,
                "height": 1152,
                "random_resolution": False,
            }

        self._trigger_generation(cv_overrides)

    def _trigger_generation(self, cv_overrides=None):
        """전송 완료 후 이미지 생성 트리거."""
        main_window = getattr(self.app_context, 'main_window', None)
        if not main_window:
            self._set_generating_state(False)
            return

        # 기존 구독이 남아있을 수 있으므로 먼저 해제
        self._unsubscribe_generation()

        # 생성 완료/에러 이벤트 구독
        self.app_context.subscribe(
            "generation_completed_for_character_viewer",
            self._on_generation_completed,
        )
        self.app_context.subscribe("generation_error", self._on_generation_error)

        try:
            main_window.generation_controller.execute_generation_pipeline(
                overrides=cv_overrides if cv_overrides else None
            )
        except Exception as e:
            print(f"[CharacterViewer] 생성 오류: {e}")
            self._unsubscribe_generation()
            self._set_generating_state(False)

    def _unsubscribe_generation(self):
        """생성 이벤트 구독 해제."""
        if not self.app_context:
            return
        for event_name, callback in [
            ("generation_completed_for_character_viewer", self._on_generation_completed),
            ("generation_error", self._on_generation_error),
        ]:
            subs = self.app_context.subscribers.get(event_name, [])
            if callback in subs:
                subs.remove(callback)

    def _on_generation_completed(self, result):
        """생성 완료 → 프리뷰 표시 + 썸네일 저장 + 연속 생성."""
        self._unsubscribe_generation()
        self._set_generating_state(False)
        if not self.isVisible():
            return
        try:
            if hasattr(result, 'mode'):  # PIL Image
                self._display_preview_image(result)
                self._save_thumbnail(result)
        except Exception as e:
            print(f"[CharacterViewer] 완료 처리 오류: {e}")
        if self.continuous_gen_cb.isChecked():
            delay_ms = self._get_automation_delay_ms()
            QTimer.singleShot(delay_ms, self._continuous_next)

    def _on_generation_error(self, error_data):
        """생성 에러 처리."""
        if isinstance(error_data, dict) and error_data.get("character_viewer_request"):
            self._unsubscribe_generation()
            self._set_generating_state(False)
            if not self.isVisible():
                return
            print(f"[CharacterViewer] 생성 에러: {error_data.get('message', 'Unknown')}")
            if self.continuous_gen_cb.isChecked():
                delay_ms = self._get_automation_delay_ms()
                QTimer.singleShot(delay_ms, self._continuous_next)

    # ==================================================================
    #  연속 생성 + 자동화 연동
    # ==================================================================

    def _on_automation_stopped(self, *args):
        """자동화 중단/완료 시 연속 생성 체크 해제."""
        if self.continuous_gen_cb.isChecked():
            self.continuous_gen_cb.setChecked(False)
            print("[CharacterViewer] 자동화 중단으로 연속 생성 해제")

    def _get_automation_delay_ms(self) -> int:
        """자동화 모듈의 생성 딜레이를 ms로 반환. 없으면 기본 500ms."""
        try:
            if self.app_context and hasattr(self.app_context, 'main_window'):
                module = getattr(self.app_context.main_window, 'automation_module', None)
                if module:
                    delay = module.get_generation_delay()
                    if delay > 0:
                        return int(delay * 1000)
        except Exception:
            pass
        return 500

    def _continuous_next(self):
        """연속 생성: 다음 캐릭터로 이동 후 생성."""
        if not self.continuous_gen_cb.isChecked() or not self.isVisible():
            return
        if self._generating:
            return

        current = self.char_list.currentIndex()
        total = self.char_proxy.rowCount()
        if total == 0:
            return

        start_row = current.row() + 1 if current.isValid() else 0
        next_idx = self._find_next_generable(start_row, total)

        if next_idx is not None:
            self.char_list.setCurrentIndex(self.char_proxy.index(next_idx, 0))
            # 딜레이는 _on_generation_completed에서 이미 적용됨
            QTimer.singleShot(300, self._on_generate_clicked)
        else:
            self.continuous_gen_cb.setChecked(False)
            print("[CharacterViewer] 연속 생성 완료: 생성 가능한 캐릭터 없음")

    def _find_next_generable(self, start_row, total):
        """다음 생성 대상 인덱스 검색. 빈 썸네일만 옵션 반영. 순환하지 않음."""
        empty_only = self.empty_thumb_only_cb.isChecked()
        for row in range(start_row, total):
            source_idx = self.char_proxy.mapToSource(self.char_proxy.index(row, 0))
            item = self.char_model.itemFromIndex(source_idx)
            gk, name = item.data(Qt.ItemDataRole.UserRole)
            if empty_only:
                key = f"{gk}::{name}"
                if key in self._thumb_index:
                    continue
            return row
        return None

    def _display_preview_image(self, pil_image):
        """PIL Image → QPixmap 변환 후 프리뷰 표시."""
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        buf.seek(0)
        qimage = QImage()
        qimage.loadFromData(buf.getvalue())
        self._preview_qimage = qimage  # GC 방지 참조 유지
        self._refresh_preview_scale()

    # ==================================================================
    #  Tags Persistence
    # ==================================================================

    def _save_tags(self):
        """Prefix/Postfix 태그를 파일에 저장."""
        try:
            data = {
                "prefix": self.prefix_edit.toPlainText(),
                "postfix": self.postfix_edit.toPlainText(),
            }
            SAVE_DIR.mkdir(parents=True, exist_ok=True)
            with open(TAGS_SAVE_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            print(f"[CharacterViewer] 태그 저장 실패: {e}")

    _DEFAULT_PREFIX = "1girl, artist:rento (rukeai), solo, cowboy shot, standing"
    _DEFAULT_POSTFIX = "simple background, white background, very aesthetic, extremely absurdres, amazing quality, masterpiece, year 2024"

    def _load_tags(self):
        """저장된 Prefix/Postfix 태그 로드."""
        if not TAGS_SAVE_PATH.exists():
            self.prefix_edit.setPlainText(self._DEFAULT_PREFIX)
            self.postfix_edit.setPlainText(self._DEFAULT_POSTFIX)
            return
        try:
            with open(TAGS_SAVE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.prefix_edit.setPlainText(data.get("prefix", ""))
            self.postfix_edit.setPlainText(data.get("postfix", ""))
        except Exception as e:
            print(f"[CharacterViewer] 태그 로드 실패: {e}")

    # ==================================================================
    #  Thumbnail System
    # ==================================================================

    def _load_thumbnail_index(self):
        """시작 시 썸네일 인덱스 로드."""
        self._thumb_index = {}
        if THUMB_INDEX_PATH.exists():
            try:
                with open(THUMB_INDEX_PATH, 'r', encoding='utf-8') as f:
                    self._thumb_index = json.load(f)
            except Exception as e:
                print(f"[CharacterViewer] 썸네일 인덱스 로드 실패: {e}")

    def _save_thumbnail(self, pil_image):
        """현재 캐릭터의 썸네일을 저장."""
        if not self._current_group_key or not self._current_char_name:
            return
        try:
            from PIL import Image
            THUMB_DIR.mkdir(parents=True, exist_ok=True)

            key = f"{self._current_group_key}::{self._current_char_name}"
            safe_name = re.sub(r'[<>:"/\\|?*]', '_', key.replace('::', '__')) + ".jpg"

            # 리사이즈 + JPEG 저장
            thumb = pil_image.copy()
            thumb.thumbnail(THUMB_MAX_SIZE, Image.Resampling.LANCZOS)
            if thumb.mode == 'RGBA':
                thumb = thumb.convert('RGB')
            thumb.save(THUMB_DIR / safe_name, "JPEG", quality=85)

            # 인덱스 업데이트
            self._thumb_index[key] = safe_name
            with open(THUMB_INDEX_PATH, 'w', encoding='utf-8') as f:
                json.dump(self._thumb_index, f, ensure_ascii=False)
        except Exception as e:
            print(f"[CharacterViewer] 썸네일 저장 실패: {e}")

    def _load_thumbnail_for_char(self, group_key, char_name):
        """캐릭터 선택 시 기존 썸네일 로드."""
        key = f"{group_key}::{char_name}"
        filename = self._thumb_index.get(key)
        if not filename:
            self.preview_label.setText("Preview")
            self._preview_qimage = None
            return
        thumb_path = THUMB_DIR / filename
        if not thumb_path.exists():
            self.preview_label.setText("Preview")
            self._preview_qimage = None
            return
        qimage = QImage(str(thumb_path))
        self._preview_qimage = qimage
        self._refresh_preview_scale()

    def _set_generating_state(self, generating: bool):
        """Generate 버튼 상태 제어."""
        self._generating = generating
        self.generate_btn.setEnabled(not generating)
        self.generate_btn.setText("Generating..." if generating else "Generate")
