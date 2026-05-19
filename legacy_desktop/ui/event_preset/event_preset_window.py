"""
Event Preset Window — NAIA 2.0 통합 메인 윈도우

viewer_multi.py PartitionBoundViewer를 NAIA 테마로 재작성.
3-Panel 레이아웃: Master-Detail Navigation | Analysis Tabs | Image+Prompt+Recommendations
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from PyQt6.QtCore import QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from legacy_desktop.ui.theme import DARK_COLORS
from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size

from core.event_preset.data_manager import EventPresetDataManager
from .download_worker import EventPresetDownloadDialog, EventPresetDownloadWorker, ThumbnailDownloadWorker
from core.event_preset.engines import (
    MAX_STAGED,
    PERSON_PARTITION_LABELS,
    PERSON_PARTITION_ORDER,
    PREFIX_TO_RATING,
    RATING_PREFIX_MAP,
    RATING_TOGGLES,
    TOP_N,
    PromptBuilder,
    QuickSearchComboProvider,
    RecommendationEngine,
    StagingEngine,
    TaxonomyEngine,
    format_count,
    parse_partition_name,
)
from .widgets import (
    ROLE_HTML,
    ComboTagDelegate,
    ImagePreviewWidget,
    RecommendedTagsPanel,
    RichComboDelegate,
    StagingBar,
    SwitchPartitionBar,
)



# ---------------------------------------------------------------------------
# 숫자 정렬 가능한 테이블 아이템
# ---------------------------------------------------------------------------

class _NumItem(QTableWidgetItem):
    """format_count 텍스트 표시 + 원본 int 기준 정렬."""

    def __init__(self, value: int) -> None:
        super().__init__(format_count(value))
        self._value = value

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, _NumItem):
            return self._value < other._value
        return super().__lt__(other)


# ---------------------------------------------------------------------------
# 파티션 HTML 포맷
# ---------------------------------------------------------------------------

def _partition_html(rating_prefix: str, person_key: str, count: int) -> str:
    rating_colors = {"g": "#4CAF50", "s": "#FF9800", "q": "#9C27B0", "e": "#F44336"}
    badge_color = rating_colors.get(rating_prefix, DARK_COLORS['text_secondary'])
    badge = f'<span style="color:{badge_color}; font-weight:700">[{rating_prefix.upper()}]</span>'
    person_label = PERSON_PARTITION_LABELS.get(person_key, person_key)
    count_str = format_count(count)
    return f'{badge}<span style="color:{DARK_COLORS["text_primary"]}"> {person_label} ({count_str})</span>'


# ---------------------------------------------------------------------------
# 백그라운드 썸네일 로더
# ---------------------------------------------------------------------------

class _ThumbnailLoader(QThread):
    """백그라운드에서 event_preset_thumbnail JSON 로딩."""
    finished = pyqtSignal(dict)

    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self._path = path

    def run(self) -> None:
        try:
            with self._path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            self.finished.emit(data)
        except Exception:
            self.finished.emit({})


# =========================================================================
# EventPresetWindow
# =========================================================================

class EventPresetWindow(QMainWindow):
    """Event Preset 메인 윈도우."""

    window_closed = pyqtSignal()
    apply_to_main_prompt = pyqtSignal(dict)

    # ------------------------------------------------------------------
    # 사전작업: 윈도우 생성 전 데이터 확인 + 다운로드
    # ------------------------------------------------------------------

    @staticmethod
    def ensure_data_available(parent=None) -> bool:
        """데이터 존재 확인. 없으면 다운로드 대화상자 표시.

        Returns: True if data is ready, False if user cancelled or download failed.
        """
        dm = EventPresetDataManager()
        if dm.is_data_available():
            # preset 존재 → 썸네일만 확인
            EventPresetWindow._ensure_thumbnail_available(parent)
            return True

        # TODO(web-dialog): 원래 QMessageBox(Yes/No) confirm + EventPresetDownloadDialog.exec() (worker sub-loop, ~385MB).
        # Web Shell 진행률 UI + confirm 모달로 재구현 필요. 안전 기본값 — 다운로드 차단.
        print("[Dialog/CONFIRM(skipped→No)] Event Preset 데이터 다운로드 confirm 차단 (~385MB) — Web Shell 재구현 예정")
        return False

    @staticmethod
    def _ensure_thumbnail_available(parent=None) -> None:
        """썸네일 파일 존재 확인. 없으면 자동 다운로드.
        TODO(web-dialog): 원래 EventPresetDownloadDialog.exec() (worker sub-loop) — Web Shell 진행률 UI 재구현 필요."""
        thumb_path = Path(__file__).resolve().parent.parent.parent / "data" / "event_preset_thumbnail"
        if thumb_path.exists():
            return
        print("[Dialog/SKIPPED] Event Preset 썸네일 다운로드 dialog 차단 — Web Shell 재구현 예정")

    # ------------------------------------------------------------------
    # 생성자
    # ------------------------------------------------------------------

    def __init__(self, app_context=None, kr_tags_df=None, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._kr_tags_df = kr_tags_df
        self._generating = False

        self.setWindowTitle("Event Preset")
        self.setMinimumSize(get_scaled_size(1680), get_scaled_size(980))
        self.resize(get_scaled_size(1960), get_scaled_size(1190))

        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """)

        # 데이터 매니저
        self._data_manager = EventPresetDataManager()

        # 엔진 (데이터 로드 후 초기화)
        self._taxonomy: TaxonomyEngine | None = None
        self._staging = StagingEngine()
        self._recommendation: RecommendationEngine | None = None

        # 상태
        self.current_event: str = ""
        self.current_rating: str = "General"
        self._base_partition = ""          # 좌측 패널 기준 파티션 (Rating + Character)
        self._step15_active_partition = "" # 실제 활성 파티션 (Switch 시 일시 변경)
        self._step15_active_data: dict[str, Any] | None = None
        self._step15_event_count_map: dict[str, int] = {}
        self._switching_partition = False
        self._search_active = False
        self._search_filter_set: set[str] | None = None
        self._partition_row_counts: dict = {}
        self._ui_ready = False  # UI 구축 완료 전 시그널 억제
        self._detail_event_items: dict[str, QTreeWidgetItem] = {}
        self._show_all_combos = False  # False=Top 100, True=All
        self._qs_combo_provider: QuickSearchComboProvider | None = None
        self._dependency_rules_df: pd.DataFrame | None = None
        self._thumbnail_data: dict[str, list[str]] = {}
        self._thumb_loader: _ThumbnailLoader | None = None

        # UI 구축
        self._build_ui()
        self._ui_ready = True

        # 데이터 로드 (ensure_data_available 통과 후이므로 데이터 존재 보장)
        self._load_and_init()

    # ------------------------------------------------------------------
    # UI 구축
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """3-Panel 레이아웃 구축."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 메인 스플리터 (2:3:5)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {DARK_COLORS['border']};
                width: 1px;
            }}
        """)

        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()

        self._splitter.setStretchFactor(0, 2)
        self._splitter.setStretchFactor(1, 3)
        self._splitter.setStretchFactor(2, 5)

        # 초기 크기 2:3:5 비율 적용 (우측 이미지 1:1 확보)
        w = get_scaled_size(1960)
        self._splitter.setSizes([w * 2 // 10, w * 3 // 10, w * 5 // 10])

        main_layout.addWidget(self._splitter)

    # ------------------------------------------------------------------
    # Left Panel: Master-Detail Navigation
    # ------------------------------------------------------------------

    def _build_left_panel(self) -> None:
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(4), get_scaled_size(8),
        )
        left_layout.setSpacing(get_scaled_size(6))

        # Rating 토글 버튼
        rating_row = QWidget()
        rating_layout = QHBoxLayout(rating_row)
        rating_layout.setContentsMargins(0, 0, 0, 0)
        rating_layout.setSpacing(get_scaled_size(4))

        self._rating_button_group = QButtonGroup(self)
        self._rating_button_group.setExclusive(True)
        self._rating_buttons: dict[str, QPushButton] = {}

        for rating in RATING_TOGGLES:
            btn = QPushButton(rating)
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    font-weight: 600;
                    padding: {get_scaled_size(4)}px {get_scaled_size(10)}px;
                    font-size: {get_scaled_font_size(17)}px;
                    background-color: {DARK_COLORS['bg_secondary']};
                    color: {DARK_COLORS['text_secondary']};
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: {get_scaled_size(3)}px;
                }}
                QPushButton:checked {{
                    background-color: {DARK_COLORS['accent_blue']};
                    color: white;
                    border: 1px solid {DARK_COLORS['accent_blue']};
                }}
                QPushButton:hover {{
                    background-color: {DARK_COLORS['bg_hover']};
                }}
                QPushButton:checked:hover {{
                    background-color: {DARK_COLORS['accent_blue_hover']};
                }}
            """)
            self._rating_button_group.addButton(btn)
            self._rating_buttons[rating] = btn
            rating_layout.addWidget(btn, stretch=1)

        left_layout.addWidget(rating_row)

        # Character 콤보 (Rating setChecked 전에 생성해야 함 — 시그널 순서)
        self._character_combo = QComboBox()
        self._character_combo.setEditable(False)
        self._character_combo.setMaxVisibleItems(13)
        self._character_combo.setItemDelegate(RichComboDelegate(self._character_combo))
        self._character_combo.setStyleSheet(f"""
            QComboBox {{
                font-size: {get_scaled_font_size(17)}px;
                padding: {get_scaled_size(4)}px;
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                selection-background-color: {DARK_COLORS['accent_blue']};
                border: 1px solid {DARK_COLORS['border']};
            }}
        """)
        self._character_combo.currentIndexChanged.connect(self._on_character_changed)
        left_layout.addWidget(self._character_combo)

        # Rating 시그널 연결 + 초기 선택 (콤보 생성 후)
        self._rating_button_group.buttonToggled.connect(self._on_rating_toggled)
        self._rating_buttons["General"].setChecked(True)

        # 검색 입력 + Clear 버튼
        search_row = QWidget()
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(get_scaled_size(4))

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search events...")
        self._search_input.setStyleSheet(f"""
            QLineEdit {{
                font-size: {get_scaled_font_size(18)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(8)}px;
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
            }}
            QLineEdit:focus {{
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
        """)
        self._search_debounce = QTimer()
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(350)
        self._search_debounce.timeout.connect(self._on_search_changed)
        self._search_input.textChanged.connect(lambda _: self._search_debounce.start())
        search_layout.addWidget(self._search_input, stretch=1)

        self._search_clear_btn = QPushButton("Clear")
        self._search_clear_btn.setStyleSheet(f"""
            QPushButton {{
                font-size: {get_scaled_font_size(16)}px;
                padding: {get_scaled_size(4)}px {get_scaled_size(8)}px;
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(3)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)
        self._search_clear_btn.clicked.connect(lambda: self._search_input.clear())
        search_layout.addWidget(self._search_clear_btn)

        left_layout.addWidget(search_row)

        # Master-Detail 스플리터 (Subgroup Tree / Event Detail)
        nav_splitter = QSplitter(Qt.Orientation.Vertical)
        nav_splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {DARK_COLORS['text_secondary']};
                height: {get_scaled_size(3)}px;
            }}
        """)

        tree_style = f"""
            QTreeWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                font-size: {get_scaled_font_size(18)}px;
                alternate-background-color: {DARK_COLORS['bg_secondary']};
            }}
            QTreeWidget::item {{
                padding: {get_scaled_size(2)}px;
            }}
            QTreeWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
            }}
            QTreeWidget::item:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """

        # Subgroup Tree (상단)
        self._subgroup_tree = QTreeWidget()
        self._subgroup_tree.setHeaderHidden(True)
        self._subgroup_tree.setIndentation(get_scaled_size(16))
        self._subgroup_tree.setAlternatingRowColors(False)
        self._subgroup_tree.setRootIsDecorated(True)
        self._subgroup_tree.setStyleSheet(tree_style)
        self._subgroup_tree.itemSelectionChanged.connect(self._on_subgroup_selected)
        nav_splitter.addWidget(self._subgroup_tree)

        # Event Detail List (하단)
        self._event_detail = QTreeWidget()
        self._event_detail.setHeaderHidden(True)
        self._event_detail.setIndentation(get_scaled_size(14))
        self._event_detail.setAlternatingRowColors(True)
        self._event_detail.setRootIsDecorated(True)
        self._event_detail.setStyleSheet(tree_style)
        self._event_detail.setExpandsOnDoubleClick(False)
        self._event_detail.clicked.connect(self._on_detail_item_clicked)
        self._event_detail.currentItemChanged.connect(self._on_detail_event_selected)
        self._event_detail.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._event_detail.customContextMenuRequested.connect(self._on_detail_context_menu)
        nav_splitter.addWidget(self._event_detail)

        nav_splitter.setStretchFactor(0, 5)
        nav_splitter.setStretchFactor(1, 3)

        left_layout.addWidget(nav_splitter, stretch=1)

        self._splitter.addWidget(left)

    # ------------------------------------------------------------------
    # Center Panel: Analysis Tabs
    # ------------------------------------------------------------------

    def _build_center_panel(self) -> None:
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(
            get_scaled_size(4), get_scaled_size(8),
            get_scaled_size(4), get_scaled_size(8),
        )
        center_layout.setSpacing(get_scaled_size(6))

        # 타이틀 행 (이벤트명 + 카운트)
        title_row = QWidget()
        title_row.setStyleSheet("background: transparent; border: none;")
        title_layout = QHBoxLayout(title_row)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(get_scaled_size(8))

        self._title_label = QLabel("Select an event")
        self._title_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(20)}px;
                font-weight: bold;
                border: none;
                background: transparent;
            }}
        """)
        title_layout.addWidget(self._title_label)

        self._title_count_label = QLabel("")
        self._title_count_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(17)}px;
                border: none;
                background: transparent;
            }}
        """)
        title_layout.addWidget(self._title_count_label)
        title_layout.addStretch()
        center_layout.addWidget(title_row)

        # 카테고리 라벨
        self._info_category_label = QLabel("")
        self._info_category_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['accent_blue']};
                font-size: {get_scaled_font_size(15)}px;
                border: none;
            }}
        """)
        self._info_category_label.setVisible(False)
        center_layout.addWidget(self._info_category_label)

        # 설명 라벨 (고정 3줄)
        self._info_desc_label = QLabel("")
        self._info_desc_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(15)}px;
                border: none;
            }}
        """)
        self._info_desc_label.setWordWrap(True)
        self._info_desc_label.setVisible(False)
        center_layout.addWidget(self._info_desc_label)

        # 키워드 라벨
        self._info_keywords_label = QLabel("")
        self._info_keywords_label.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(14)}px;
                font-style: italic;
                border: none;
            }}
        """)
        self._info_keywords_label.setWordWrap(True)
        self._info_keywords_label.setVisible(False)
        center_layout.addWidget(self._info_keywords_label)

        # Staging Bar
        self._staging_bar = StagingBar()
        self._staging_bar.clear_requested.connect(self._clear_staging)
        center_layout.addWidget(self._staging_bar)

        # Switch-to Partition Bar + Full Mode 체크박스
        switch_row = QWidget()
        switch_row_layout = QHBoxLayout(switch_row)
        switch_row_layout.setContentsMargins(0, 0, 0, 0)
        switch_row_layout.setSpacing(get_scaled_size(8))

        self._switch_bar = SwitchPartitionBar()
        self._switch_bar.partition_selected.connect(self._on_switch_partition_selected)
        switch_row_layout.addWidget(self._switch_bar, stretch=1)

        self._full_mode_cb = QCheckBox("Full Mode")
        self._full_mode_cb.setToolTip("Show all observed combos instead of top 100")
        self._full_mode_cb.setStyleSheet(f"""
            QCheckBox {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(15)}px;
                spacing: {get_scaled_size(4)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(14)}px;
                height: {get_scaled_size(14)}px;
            }}
        """)
        self._full_mode_cb.toggled.connect(self._on_combo_full_mode_toggled)
        switch_row_layout.addWidget(self._full_mode_cb)

        center_layout.addWidget(switch_row)

        # 분석 탭
        tab_style = f"""
            QTabWidget::pane {{
                border: 1px solid {DARK_COLORS['border']};
                background-color: {DARK_COLORS['bg_primary']};
            }}
            QTabBar::tab {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                font-size: {get_scaled_font_size(17)}px;
                border: 1px solid {DARK_COLORS['border']};
                border-bottom: none;
                border-top-left-radius: {get_scaled_size(3)}px;
                border-top-right-radius: {get_scaled_size(3)}px;
            }}
            QTabBar::tab:selected {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
            QTabBar::tab:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(tab_style)

        # Observed Combos 탭 (최상위)
        self._combo_table = self._new_table(["Observed Event Combo", "Count"])
        self._combo_table.setWordWrap(True)
        self._combo_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._combo_tag_delegate = ComboTagDelegate(self._combo_table)
        self._combo_table.setItemDelegateForColumn(0, self._combo_tag_delegate)
        combo_header = self._combo_table.horizontalHeader()
        combo_header.setStretchLastSection(False)
        combo_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        combo_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._combo_table.setColumnWidth(1, get_scaled_size(55))
        self._combo_table.currentCellChanged.connect(self._on_combo_selected)
        self._tabs.addTab(self._combo_table, "Observed Combos")

        # Expression / Clothing / Characteristic 탭 (공통 Count+Confidence 고정 너비)
        for attr, label, tag in [
            ("_expr_table", "Expression", "Expression"),
            ("_cloth_table", "Clothing", "Clothing"),
            ("_char_table", "Characteristic", "Characteristic"),
        ]:
            tbl = self._new_table([tag, "Count", "Confidence"])
            h = tbl.horizontalHeader()
            h.setStretchLastSection(False)
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            h.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
            h.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
            tbl.setColumnWidth(1, get_scaled_size(55))
            tbl.setColumnWidth(2, get_scaled_size(75))
            setattr(self, attr, tbl)
            self._tabs.addTab(tbl, label)

        center_layout.addWidget(self._tabs, stretch=1)
        self._splitter.addWidget(center)

    def _new_table(self, headers: list[str]) -> QTableWidget:
        """NAIA 테마 적용 테이블 생성."""
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setMouseTracking(False)
        table.viewport().setMouseTracking(False)

        header = table.horizontalHeader()
        header.setStretchLastSection(True)

        table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                gridline-color: {DARK_COLORS['border']};
                border: 1px solid {DARK_COLORS['border']};
                font-size: {get_scaled_font_size(19)}px;
                alternate-background-color: {DARK_COLORS['bg_secondary']};
            }}
            QTableWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
            }}
            QTableWidget::item:hover {{
                background-color: transparent;
            }}
            QTableWidget::item:hover:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
            }}
            QHeaderView::section {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                padding: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(19)}px;
                font-weight: 600;
                border: 1px solid {DARK_COLORS['border']};
            }}
        """)
        return table

    # ------------------------------------------------------------------
    # Right Panel: Image + Prompt + Recommendations
    # ------------------------------------------------------------------

    def _build_right_panel(self) -> None:
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(
            get_scaled_size(4), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8),
        )
        right_layout.setSpacing(get_scaled_size(8))

        # 이미지 프리뷰
        self._image_preview = ImagePreviewWidget()
        right_layout.addWidget(self._image_preview, stretch=1)

        # 추천 태그 패널
        self._rec_panel = RecommendedTagsPanel()
        self._rec_panel.chip_toggled.connect(self._on_chip_toggled)
        right_layout.addWidget(self._rec_panel)

        # 프롬프트 편집
        self._prompt_edit = QTextEdit()
        self._prompt_edit.setAcceptRichText(False)
        self._prompt_edit.setPlaceholderText("Select an Observed Combo to generate prompt...")
        self._prompt_edit.setMaximumHeight(get_scaled_size(120))
        self._prompt_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                color: {DARK_COLORS['text_primary']};
                font-size: {get_scaled_font_size(20)}px;
                padding: {get_scaled_size(6)}px;
                border-radius: {get_scaled_size(3)}px;
            }}
        """)
        right_layout.addWidget(self._prompt_edit)

        # 버튼 행
        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)

        # 메인 프롬프트에 전송 버튼
        self._send_to_main_btn = QPushButton("메인 프롬프트에 전송")
        self._send_to_main_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                border-radius: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(14)}px;
                border: 1px solid {DARK_COLORS['border']};
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['border']};
            }}
        """)
        self._send_to_main_btn.clicked.connect(self._on_send_to_main)
        btn_layout.addWidget(self._send_to_main_btn)

        # 전송 + 즉시 생성 버튼
        self._send_and_gen_btn = QPushButton("전송 + 즉시 생성")
        self._send_and_gen_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
                padding: {get_scaled_size(6)}px {get_scaled_size(12)}px;
                border-radius: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(14)}px;
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['border']};
            }}
        """)
        self._send_and_gen_btn.clicked.connect(self._on_send_and_generate)
        btn_layout.addWidget(self._send_and_gen_btn)

        btn_layout.addStretch()

        # 파이프라인 안내 라벨
        pipeline_note = QLabel("* 메인화면 설정값, 선행/후행 고정 프롬프트를 사용합니다.")
        pipeline_note.setStyleSheet(f"""
            QLabel {{
                color: {DARK_COLORS['text_secondary']};
                font-size: {get_scaled_font_size(14)}px;
                border: none;
                background: transparent;
            }}
        """)
        btn_layout.addWidget(pipeline_note)

        # Generate 버튼
        self._generate_btn = QPushButton("Generate")
        self._generate_btn.setFixedWidth(get_scaled_size(130))
        self._generate_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                font-weight: 600;
                padding: {get_scaled_size(6)}px {get_scaled_size(16)}px;
                border-radius: {get_scaled_size(4)}px;
                font-size: {get_scaled_font_size(19)}px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_disabled']};
            }}
        """)
        self._generate_btn.clicked.connect(self._on_generate_clicked)
        btn_layout.addWidget(self._generate_btn)
        right_layout.addWidget(btn_row)

        self._splitter.addWidget(right)

    # ------------------------------------------------------------------
    # 데이터 로딩
    # ------------------------------------------------------------------

    def _load_and_init(self) -> None:
        """데이터 로드 + 엔진 초기화."""
        try:
            assets, missing = self._data_manager.load_base_assets()
            if assets is None:
                self._title_label.setText(f"필수 파일 누락: {', '.join(missing)}")
                return

            self._taxonomy = TaxonomyEngine(assets)
            self._recommendation = RecommendationEngine(
                self._data_manager.get_recommendations(),
                self._data_manager.get_color_prefixes(),
            )
            self._partition_row_counts = self._data_manager.get_partition_row_counts()
            self._dependency_rules_df = assets.get("dependency_rules.parquet")

            # Quick Search combo provider (데이터 미설치 시 None — Full Mode 토글 시 다운로드 유도)
            self._qs_combo_provider = QuickSearchComboProvider.try_create(
                self._taxonomy.category,
                self._dependency_rules_df,
            )

            # 파티션 바인딩
            self._refresh_character_combo()
            self._refresh_partition_binding()

            self._title_label.setText("Select an event")

            # 썸네일 백그라운드 로딩
            thumb_path = Path(__file__).resolve().parent.parent.parent / "data" / "event_preset_thumbnail"
            if thumb_path.exists():
                self._thumb_loader = _ThumbnailLoader(thumb_path, parent=self)
                self._thumb_loader.finished.connect(self._on_thumbnails_loaded)
                self._thumb_loader.start()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._title_label.setText(f"데이터 로드 오류: {e}")

    # ------------------------------------------------------------------
    # 파티션 관리
    # ------------------------------------------------------------------

    def _get_selected_partition_name(self) -> str:
        """현재 Rating + Character → 파티션 이름."""
        prefix = RATING_PREFIX_MAP.get(self.current_rating, "g")
        person_key = self._character_combo.currentData()
        if not person_key:
            return ""
        return f"{prefix}_{person_key}"

    def _refresh_character_combo(self) -> None:
        """현재 Rating에 맞는 Character 콤보 갱신."""
        self._character_combo.blockSignals(True)
        self._character_combo.clear()

        prefix = RATING_PREFIX_MAP.get(self.current_rating, "g")
        rating_label = {"g": "General", "s": "Sensitive", "q": "Question", "e": "Explicit"}.get(prefix, "General")
        counts = self._partition_row_counts.get(rating_label, {})
        available = self._data_manager.get_available_partitions()

        for person_key in PERSON_PARTITION_ORDER:
            partition_name = f"{prefix}_{person_key}"
            if partition_name not in available:
                continue
            row_count = counts.get(person_key, 0)
            display_text = f"{PERSON_PARTITION_LABELS.get(person_key, person_key)} ({format_count(row_count)})"
            html = _partition_html(prefix, person_key, row_count)
            self._character_combo.addItem(display_text, person_key)
            idx = self._character_combo.count() - 1
            self._character_combo.setItemData(idx, html, ROLE_HTML)

        self._character_combo.blockSignals(False)

    def _refresh_partition_binding(self) -> None:
        """현재 파티션 데이터 로딩 + 트리 갱신."""
        if self._taxonomy is None:
            return

        self._staging.clear_staging()
        self._staging_bar.update_staging([])
        if self._recommendation:
            self._recommendation.reset_states()

        partition_name = self._get_selected_partition_name()
        self._base_partition = partition_name
        self._step15_active_partition = partition_name

        # Switch 라벨에 현재 rating prefix 배지 표시
        if partition_name:
            try:
                prefix, _ = parse_partition_name(partition_name)
                self._switch_bar.set_current_rating(prefix)
            except (ValueError, IndexError):
                pass

        if not partition_name:
            self._step15_active_data = None
            self._step15_event_count_map = {}
            self._taxonomy.reset_to_base()
            self._reapply_search_or_navigation()
            return

        available = self._data_manager.get_available_partitions()
        if partition_name not in available:
            self._step15_active_data = None
            self._step15_event_count_map = {}
            self._taxonomy.reset_to_base()
            self._reapply_search_or_navigation()
            self._title_count_label.setText(f"파티션 없음: {partition_name}")
            return

        try:
            data = self._data_manager.load_partition_data(partition_name)
        except Exception as e:
            self._step15_active_data = None
            self._step15_event_count_map = {}
            self._taxonomy.reset_to_base()
            self._reapply_search_or_navigation()
            self._title_count_label.setText(f"로드 실패: {e}")
            return

        self._step15_active_data = data

        # 이벤트 카운트 맵
        catalog = data.get("catalog", pd.DataFrame())
        if isinstance(catalog, pd.DataFrame) and len(catalog) > 0:
            self._step15_event_count_map = {
                str(r.event_tag): int(r.post_count)
                for r in catalog[["event_tag", "post_count"]].itertuples(index=False)
            }
        else:
            self._step15_event_count_map = {}

        self._taxonomy.apply_partition_projection(self._step15_event_count_map)
        self._reapply_search_or_navigation()

        # 현재 이벤트 재표시
        if self.current_event:
            self._on_event_selected(self.current_event)

    # ------------------------------------------------------------------
    # 네비게이션 트리
    # ------------------------------------------------------------------

    def _refresh_navigation(self, filter_events: set[str] | None = None) -> None:
        """Subgroup 트리 + Event Detail 갱신."""
        if self._taxonomy is None:
            return

        self._subgroup_tree.clear()
        self._event_detail.clear()

        subgroups = self._taxonomy.get_subgroups_sorted()
        if not subgroups:
            return

        # 필터
        if filter_events is not None:
            visible = filter_events
        else:
            visible = set(self._step15_event_count_map.keys()) if self._step15_event_count_map else None

        # Group → Subgroup 트리
        current_group = ""
        group_item: QTreeWidgetItem | None = None

        for sg in subgroups:
            group = sg["group"]
            # 필터링: 이 서브그룹에 해당하는 이벤트가 있는지 확인
            events = self._taxonomy.get_events_for_subgroup(group, sg["subgroup"])
            if visible is not None:
                events = [e for e in events if e["event_tag"] in visible]
            if not events:
                continue

            if group != current_group:
                group_item = QTreeWidgetItem([sg["group_display"]])
                group_item.setFlags(group_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self._subgroup_tree.addTopLevelItem(group_item)
                current_group = group

            total = sum(e["post_count"] for e in events)
            text = f"{sg['subgroup_display']} ({format_count(total)})"
            sub_item = QTreeWidgetItem([text])
            sub_item.setData(0, Qt.ItemDataRole.UserRole, (group, sg["subgroup"]))
            if group_item:
                group_item.addChild(sub_item)

        # 첫 번째 그룹 확장 + 첫 서브그룹 선택
        self._subgroup_tree.expandAll()
        self._select_first_subgroup()

    def _select_first_subgroup(self) -> None:
        """첫 번째 선택 가능한 서브그룹 자동 선택."""
        for i in range(self._subgroup_tree.topLevelItemCount()):
            group_item = self._subgroup_tree.topLevelItem(i)
            if group_item and group_item.childCount() > 0:
                child = group_item.child(0)
                if child:
                    self._subgroup_tree.setCurrentItem(child)
                    return

    def _on_subgroup_selected(self) -> None:
        """서브그룹 선택 → Event Detail 갱신."""
        if self._taxonomy is None:
            return

        items = self._subgroup_tree.selectedItems()
        if not items:
            return

        item = items[0]
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        group, subgroup = data
        events = self._taxonomy.get_events_for_subgroup(group, subgroup)

        # 파티션 필터링
        visible = set(self._step15_event_count_map.keys()) if self._step15_event_count_map else None
        if visible is not None:
            events = [e for e in events if e["event_tag"] in visible]

        # 검색 필터 교차: 검색 활성 시 매칭 이벤트만 표시
        if self._search_active and self._search_filter_set is not None:
            events = [e for e in events if e["event_tag"] in self._search_filter_set]

        # Event Detail 트리 갱신
        self._event_detail.clear()
        self._detail_event_items: dict[str, QTreeWidgetItem] = {}

        # 서브카테고리별 그룹핑
        current_subcat = ""
        subcat_item: QTreeWidgetItem | None = None

        for ev in events:
            subcat = ev.get("subcategory", "")
            subcat_display = ev.get("subcategory_display", "")

            if subcat and subcat != current_subcat:
                subcat_item = QTreeWidgetItem([subcat_display or subcat])
                subcat_item.setFlags(subcat_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                subcat_item.setBackground(0, QBrush(QColor("#DDDDDD")))
                subcat_item.setForeground(0, QBrush(QColor("#111111")))
                self._event_detail.addTopLevelItem(subcat_item)
                current_subcat = subcat
            elif not subcat and current_subcat:
                subcat_item = None
                current_subcat = ""

            count = ev["post_count"]
            text = f"{ev['event_tag']} ({format_count(count)})"
            event_item = QTreeWidgetItem([text])
            event_item.setData(0, Qt.ItemDataRole.UserRole, ev["event_tag"])

            if subcat_item:
                subcat_item.addChild(event_item)
            else:
                self._event_detail.addTopLevelItem(event_item)

            self._detail_event_items[ev["event_tag"]] = event_item

        self._event_detail.collapseAll()

    def _on_detail_item_clicked(self, index) -> None:
        """Event Detail 단일 클릭 시 자식이 있는 항목 펼침/닫힘 토글."""
        item = self._event_detail.itemFromIndex(index)
        if item and item.childCount() > 0:
            self._event_detail.setExpanded(index, not self._event_detail.isExpanded(index))

    def _on_detail_event_selected(self, current: QTreeWidgetItem | None, _prev) -> None:
        """Event Detail에서 이벤트 선택."""
        if current is None:
            return
        event_name = current.data(0, Qt.ItemDataRole.UserRole)
        if not event_name:
            return
        self._on_event_selected(event_name)

    # ------------------------------------------------------------------
    # 이벤트 선택 처리
    # ------------------------------------------------------------------

    def _on_event_selected(self, event_name: str) -> None:
        """이벤트 선택 시 모든 패널 갱신."""
        self.current_event = event_name
        self._title_label.setText(event_name)
        self._update_tag_info(event_name)

        # Switch 파티션이 일시 적용 중이면 기본 파티션으로 복귀
        if self._step15_active_partition != self._base_partition and self._base_partition:
            self._revert_to_base_partition()

        # (선택된 추천 태그는 유지 — 사용자가 Clear 버튼으로 수동 초기화)

        if self._step15_active_data is None:
            self._combo_table.setRowCount(0)
            self._title_count_label.setText("파티션 데이터 없음")
            return

        # Observed Combos 채우기
        self._fill_observed_combos(event_name)

        # Expression/Clothing/Characteristic 테이블 채우기
        self._fill_cooccurrence_tables(event_name)

        # 추천 태그 갱신
        self._update_recommendations([event_name])

        # Switch-to 파티션 콤보
        self._update_switch_to_combo(event_name)

        # 썸네일 표시
        self._show_event_thumbnail(event_name)

    # ------------------------------------------------------------------
    # 썸네일 표시
    # ------------------------------------------------------------------

    def _on_thumbnails_loaded(self, data: dict) -> None:
        """백그라운드 썸네일 JSON 로딩 완료."""
        self._thumbnail_data = data
        print(f"[EventPreset] 썸네일 로딩 완료: {len(data)}개")
        if self.current_event:
            self._show_event_thumbnail(self.current_event)

    def _show_event_thumbnail(self, event_name: str) -> None:
        """이벤트 썸네일을 _image_preview에 표시."""
        if not self._thumbnail_data:
            return
        b64_list = self._thumbnail_data.get(event_name)
        if b64_list:
            self._image_preview.display_base64(b64_list[0])
        else:
            self._image_preview.clear_image()

    def _update_tag_info(self, event_name: str) -> None:
        """센터 상단 KR_tags 정보 갱신."""
        # 기본값: 정보 없으면 숨김
        self._title_count_label.setText("")
        self._info_category_label.setVisible(False)
        self._info_desc_label.setVisible(False)
        self._info_keywords_label.setVisible(False)

        if self._kr_tags_df is None or self._kr_tags_df.empty or not event_name:
            return
        rows = self._kr_tags_df[self._kr_tags_df["tag"] == event_name]
        if rows.empty:
            return

        data = rows.iloc[0]
        count_val = data.get("count", None)
        if pd.notna(count_val):
            self._title_count_label.setText(f"{int(count_val):,}")

        category = str(data.get("category", "")) if pd.notna(data.get("category")) else ""
        if category:
            self._info_category_label.setText(category)
            self._info_category_label.setVisible(True)

        desc = str(data.get("desc", "")) if pd.notna(data.get("desc")) else ""
        if desc:
            self._info_desc_label.setText(desc)
            self._info_desc_label.setVisible(True)

        keywords = str(data.get("keywords", "")) if pd.notna(data.get("keywords")) else ""
        if keywords:
            self._info_keywords_label.setText(f"Keywords: {keywords}")
            self._info_keywords_label.setVisible(True)

    def _fill_observed_combos(self, event_name: str) -> None:
        """Observed Combos 테이블 채우기."""
        # 현재 셀 초기화 (이전과 동일한 (0,0)일 때 시그널 미발생 방지)
        self._combo_table.setCurrentCell(-1, -1)

        # 델리게이트에 현재 이벤트 태그 전달
        highlight = {event_name} | set(self._staging.staged_events)
        self._combo_tag_delegate.set_event_tags(highlight)

        if self._show_all_combos:
            # Full Mode: event_combo_index 우선, 없으면 step15 파티션 fallback
            combos = self._get_raw_combos(event_name)
            if not combos:
                combos = self._get_partition_combos(event_name)
        elif self._step15_active_data is not None:
            combos = self._get_partition_combos(event_name)
        else:
            self._combo_table.setRowCount(0)
            return

        self._combo_table.setUpdatesEnabled(False)
        self._combo_table.setSortingEnabled(False)
        self._combo_table.setRowCount(len(combos))
        for row_idx, (combo_text, count_or_score) in enumerate(combos):
            self._combo_table.setItem(row_idx, 0, QTableWidgetItem(combo_text))
            self._combo_table.setItem(row_idx, 1, _NumItem(int(count_or_score)))
        self._combo_table.setSortingEnabled(True)
        self._combo_table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self._combo_table.setUpdatesEnabled(True)

        self._combo_table.scrollToTop()
        if self._combo_table.rowCount() > 0:
            self._combo_table.setCurrentCell(0, 0)

    def _get_partition_combos(self, event_name: str) -> list[tuple[str, int | float]]:
        """step15 파티션 데이터에서 콤보 조회."""
        if self._step15_active_data is None:
            return []
        combo_df = self._step15_active_data.get("combo", pd.DataFrame())
        if combo_df.empty:
            return []
        limit = None if self._show_all_combos else TOP_N
        if self._staging.staged_events and event_name not in self._staging.staged_events:
            return self._staging.get_multi_event_combos(event_name, combo_df, limit=limit)
        return self._staging.get_single_event_combos(event_name, combo_df, limit=limit)

    def _get_raw_combos(self, event_name: str) -> list[tuple[str, int]]:
        """Full Mode: Quick Search 우선, event_combo_index fallback."""
        # Tier 1: Quick Search .tgp
        if self._qs_combo_provider is not None:
            partition = self._step15_active_partition or self._base_partition
            combos = self._qs_combo_provider.get_combos(event_name, partition)
            if combos:
                return combos

        # Tier 2: event_combo_index (기존 fallback)
        if self._taxonomy is None:
            return []
        idx = self._taxonomy.event_combo_index
        if not idx:
            return []
        lookup_key = event_name.replace(" ", "_")
        counter = idx.get(lookup_key) or idx.get(event_name)
        if not counter:
            return []
        return [
            (", ".join(tag.replace("_", " ") for tag in combo), count)
            for combo, count in counter.most_common(1000)
        ]

    def _on_combo_full_mode_toggled(self, checked: bool) -> None:
        """Full Mode 토글 — Top 100 ↔ 전체 콤보. 데이터 없으면 다운로드 유도."""
        if checked and self._qs_combo_provider is None:
            self._full_mode_cb.setChecked(False)
            if self._prompt_qs_download():
                self._qs_combo_provider = QuickSearchComboProvider.try_create(
                    self._taxonomy.category,
                    self._dependency_rules_df,
                )
                if self._qs_combo_provider is not None:
                    self._full_mode_cb.setChecked(True)
            return

        self._show_all_combos = checked
        if self.current_event:
            self._fill_observed_combos(self.current_event)

    def _prompt_qs_download(self) -> bool:
        """Quick Search 데이터 다운로드 유도. True=성공.
        TODO(web-dialog): 원래 QMessageBox(Yes/No) confirm + EventPresetDownloadDialog.exec() — Web Shell 진행률 UI 재구현 필요."""
        print("[Dialog/CONFIRM(skipped→No)] Full Mode/Quick Search 데이터 다운로드 confirm 차단 (~238MB) — Web Shell 재구현 예정")
        return False

    def _fill_cooccurrence_tables(self, event_name: str) -> None:
        """Expression/Clothing/Characteristic 테이블 채우기."""
        if self._step15_active_data is None:
            return

        # Expression
        expr_df = self._step15_active_data.get("expression", pd.DataFrame())
        self._fill_cooc_table(self._expr_table, expr_df, "expression_tag", event_name)

        # Clothing
        cloth_df = self._step15_active_data.get("clothing", pd.DataFrame())
        self._fill_cooc_table(self._cloth_table, cloth_df, "clothing_tag", event_name)

        # Characteristic
        char_df = self._step15_active_data.get("characteristic", pd.DataFrame())
        self._fill_cooc_table(self._char_table, char_df, "characteristic_tag", event_name)

    def _fill_cooc_table(
        self, table: QTableWidget, df: pd.DataFrame, tag_col: str, event_name: str,
    ) -> None:
        if df.empty or tag_col not in df.columns:
            table.setRowCount(0)
            return
        sub = df[df["event_tag"] == event_name].sort_values("confidence", ascending=False).head(TOP_N)
        table.setSortingEnabled(False)
        table.setRowCount(len(sub))
        for row_idx, (_, row) in enumerate(sub.iterrows()):
            table.setItem(row_idx, 0, QTableWidgetItem(str(row[tag_col])))
            table.setItem(row_idx, 1, _NumItem(int(row.get("count", 0))))
            conf_item = QTableWidgetItem(f"{float(row.get('confidence', 0)):.3f}")
            table.setItem(row_idx, 2, conf_item)
        table.setSortingEnabled(True)
        table.scrollToTop()
        if table.rowCount() > 0:
            table.setCurrentCell(0, 0)

    # ------------------------------------------------------------------
    # 추천 태그
    # ------------------------------------------------------------------

    def _update_recommendations(self, event_names: list[str]) -> None:
        """추천 태그 패널 갱신."""
        if self._recommendation is None or self._step15_active_data is None:
            self._rec_panel.clear()
            return

        # 자동 의존성
        auto_deps = self._recommendation.collect_auto_deps(event_names)

        # 계층 정보
        parent, root = self._recommendation.get_hierarchy_info(event_names)
        hier_text = ""
        if parent or root:
            parts = []
            if parent:
                parts.append(f"parent: {parent}")
            if root:
                parts.append(f"root: {root}")
            hier_text = " | ".join(parts)
        self._rec_panel.set_hier_info(hier_text)

        # 공기 태그 (affinity 적용)
        active = self._rec_panel.get_active_tag_list()
        affinity = self._recommendation.get_affinity_events(active, self._step15_active_data)
        cooc = self._recommendation.merge_cooccurrence(event_names, self._step15_active_data, affinity)

        self._rec_panel.refresh_chips(
            cooc.get("expr", []),
            cooc.get("cloth", []),
            cooc.get("char", []),
            auto_deps=auto_deps,
        )

    def _on_chip_toggled(self, tag: str, checked: bool) -> None:
        """칩 토글 → 추천 갱신 + 프롬프트 재조립."""
        if not tag:
            # Clear 버튼에서 발행된 시그널 — 엔진 상태도 초기화
            if self._recommendation:
                self._recommendation.active_rec_tags.clear()
        elif self._recommendation:
            self._recommendation.set_chip_state(tag, checked)

        event_names = self._get_current_event_names()
        if event_names:
            self._update_recommendations(event_names)
        self._rebuild_prompt()

    # ------------------------------------------------------------------
    # 콤보 선택 + 프롬프트
    # ------------------------------------------------------------------

    def _on_combo_selected(self, row: int, _col: int, _prev_row: int, _prev_col: int) -> None:
        """Combo 행 선택 시 프롬프트 재조립 + 추천 갱신."""
        if row < 0:
            return

        event_names = self._get_current_event_names()
        if event_names:
            self._update_recommendations(event_names)
        self._rebuild_prompt()

    def _get_current_event_names(self) -> list[str]:
        """현재 콤보 테이블 선택에서 이벤트 이름 추출."""
        row = self._combo_table.currentRow()
        if row < 0:
            return [self.current_event] if self.current_event else []

        item = self._combo_table.item(row, 0)
        if item is None:
            return [self.current_event] if self.current_event else []

        combo_text = item.text()
        events = []
        for ev in (t.strip() for t in combo_text.split(",") if t.strip()):
            if ev.startswith("[") and ev.endswith("]"):
                events.append(ev[1:-1])
            else:
                events.append(ev)
        return events if events else ([self.current_event] if self.current_event else [])

    def _rebuild_prompt(self) -> None:
        """프롬프트 재조립. 활성 파티션 기준으로 person/rating 결정."""
        events = self._get_current_event_names()

        if not events:
            return

        # 활성 파티션에서 person_category / rating 추출
        # (Switch로 파티션이 바뀌었을 수 있으므로 좌측 패널 값 대신 파티션명 파싱)
        if self._step15_active_partition:
            try:
                prefix, person_category = parse_partition_name(self._step15_active_partition)
                rating = PREFIX_TO_RATING.get(prefix, self.current_rating)
            except (ValueError, IndexError):
                person_category = str(self._character_combo.currentData() or "")
                rating = self.current_rating
        else:
            person_category = str(self._character_combo.currentData() or "")
            rating = self.current_rating

        auto_deps = self._recommendation.auto_dep_tags if self._recommendation else []
        active_recs = self._rec_panel.get_active_tag_list()

        prompt = PromptBuilder.build(
            person_category=person_category,
            rating=rating,
            event_names=events,
            auto_dep_tags=auto_deps,
            active_rec_tags=active_recs,
        )
        self._prompt_edit.setPlainText(prompt)

    # ------------------------------------------------------------------
    # Switch-to 파티션
    # ------------------------------------------------------------------

    def _update_switch_to_combo(self, event_name: str) -> None:
        """이벤트의 다른 파티션 목록으로 Switch-to 콤보 갱신."""
        index = self._data_manager.get_event_partition_index()
        partitions = index.get(event_name, [])

        current_label = ""
        items: list[tuple[str, str, str]] = []
        for entry in partitions:
            if isinstance(entry, list) and len(entry) >= 2:
                part_name, part_count = entry[0], entry[1]
            else:
                continue
            try:
                prefix, person_key = parse_partition_name(part_name)
            except (ValueError, IndexError):
                continue
            display = f"{PERSON_PARTITION_LABELS.get(person_key, person_key)} ({format_count(part_count)})"
            if part_name == self._step15_active_partition:
                current_label = display
                continue
            html = _partition_html(prefix, person_key, part_count)
            items.append((display, part_name, html))

        self._switch_bar.populate(items, current_label=current_label)

    def _on_switch_partition_selected(self, partition_name: str) -> None:
        """Switch-to 파티션 전환 — 센터 패널 데이터만 갱신 (좌측 패널 유지)."""
        if not partition_name or partition_name == self._step15_active_partition:
            return

        available = self._data_manager.get_available_partitions()
        if partition_name not in available:
            return

        try:
            data = self._data_manager.load_partition_data(partition_name)
        except Exception:
            return

        # Full Mode 해제 (파티션 전환 시 대량 로드 방지)
        if self._show_all_combos:
            self._show_all_combos = False
            self._full_mode_cb.setChecked(False)

        # 파티션 데이터만 교체 (좌측 패널 상태 유지)
        self._step15_active_partition = partition_name
        self._step15_active_data = data

        # Switch 라벨에 현재 rating prefix 배지 표시
        try:
            prefix, _ = parse_partition_name(partition_name)
            self._switch_bar.set_current_rating(prefix)
        except (ValueError, IndexError):
            pass

        catalog = data.get("catalog", pd.DataFrame())
        if isinstance(catalog, pd.DataFrame) and len(catalog) > 0:
            self._step15_event_count_map = {
                str(r.event_tag): int(r.post_count)
                for r in catalog[["event_tag", "post_count"]].itertuples(index=False)
            }
        else:
            self._step15_event_count_map = {}

        # 현재 이벤트의 분석 탭만 갱신
        if self.current_event:
            self._fill_observed_combos(self.current_event)
            self._fill_cooccurrence_tables(self.current_event)
            self._update_recommendations([self.current_event])
            self._update_switch_to_combo(self.current_event)
            self._rebuild_prompt()

    def _revert_to_base_partition(self) -> None:
        """Switch 일시 파티션을 기본 파티션으로 복귀."""
        self._step15_active_partition = self._base_partition

        try:
            prefix, _ = parse_partition_name(self._base_partition)
            self._switch_bar.set_current_rating(prefix)
        except (ValueError, IndexError):
            pass

        try:
            data = self._data_manager.load_partition_data(self._base_partition)
        except Exception:
            self._step15_active_data = None
            self._step15_event_count_map = {}
            return

        self._step15_active_data = data
        catalog = data.get("catalog", pd.DataFrame())
        if isinstance(catalog, pd.DataFrame) and len(catalog) > 0:
            self._step15_event_count_map = {
                str(r.event_tag): int(r.post_count)
                for r in catalog[["event_tag", "post_count"]].itertuples(index=False)
            }
        else:
            self._step15_event_count_map = {}

    # ------------------------------------------------------------------
    # Rating / Character 변경
    # ------------------------------------------------------------------

    def _on_rating_toggled(self, button, checked: bool) -> None:
        if not checked:
            return
        self.current_rating = button.text()
        if self._switching_partition:
            return
        # 데이터 로드 전에는 콤보/파티션 갱신 불필요
        if self._taxonomy is None:
            return
        self._refresh_character_combo()
        self._refresh_partition_binding()

    def _on_character_changed(self, _index: int) -> None:
        if self._switching_partition or self._taxonomy is None:
            return
        self._refresh_partition_binding()

    # ------------------------------------------------------------------
    # 검색
    # ------------------------------------------------------------------

    def _reapply_search_or_navigation(self) -> None:
        """검색 활성 상태이면 검색을 재실행, 아니면 일반 네비게이션 갱신."""
        if self._search_active and self._search_input.text().strip():
            self._on_search_changed()
        else:
            self._refresh_navigation()

    def _on_search_changed(self) -> None:
        if self._taxonomy is None:
            return

        needle = self._search_input.text().strip().lower()
        if not needle:
            self._search_active = False
            self._search_filter_set = None
            self._refresh_navigation()
            return

        if len(needle) < 2:
            return

        self._search_active = True
        matching = set(self._taxonomy.filter_events(needle))
        if self._step15_event_count_map:
            matching &= set(self._step15_event_count_map.keys())
        self._search_filter_set = matching

        # 서브그룹 트리 갱신 (매칭 이벤트가 있는 그룹만)
        self._refresh_navigation(filter_events=matching)

        # Event Detail에 전체 매칭 이벤트를 flat 표시
        self._refresh_event_detail_flat(matching, needle)

    def _refresh_event_detail_flat(
        self, matching: set[str], needle: str,
    ) -> None:
        """검색 매칭 이벤트를 관련성 순으로 Event Detail에 flat 표시."""
        self._event_detail.clear()
        self._detail_event_items = {}

        if not matching:
            return

        # 관련성 정렬: 완전일치 → 접두사 → 부분일치, 같은 등급 내 post_count 내림차순
        def sort_key(name: str):
            ln = name.lower()
            if ln == needle:
                tier = 0
            elif ln.startswith(needle):
                tier = 1
            else:
                tier = 2
            count = self._step15_event_count_map.get(name, 0)
            return (tier, -count, name)

        sorted_events = sorted(matching, key=sort_key)

        for ev_name in sorted_events:
            count = self._step15_event_count_map.get(ev_name, 0)
            text = f"{ev_name} ({format_count(count)})"
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.ItemDataRole.UserRole, ev_name)
            self._event_detail.addTopLevelItem(item)
            self._detail_event_items[ev_name] = item

        # 첫 번째 항목 자동 선택
        if self._event_detail.topLevelItemCount() > 0:
            first = self._event_detail.topLevelItem(0)
            if first:
                self._event_detail.setCurrentItem(first)

    # ------------------------------------------------------------------
    # Staging (우클릭 컨텍스트 메뉴)
    # ------------------------------------------------------------------

    def _on_detail_context_menu(self, pos) -> None:
        item = self._event_detail.itemAt(pos)
        if item is None:
            return
        event_name = item.data(0, Qt.ItemDataRole.UserRole)
        if not event_name:
            return

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                font-size: {get_scaled_font_size(18)}px;
            }}
            QMenu::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
        """)

        if self._staging.is_staged(event_name):
            unstage = menu.addAction(f"Unstage: {event_name}")
            unstage.triggered.connect(lambda: self._unstage_event(event_name))
        else:
            if len(self._staging.staged_events) < MAX_STAGED:
                stage = menu.addAction(f"Stage: {event_name}")
                stage.triggered.connect(lambda: self._stage_event(event_name))
            else:
                action = menu.addAction(f"Stage limit reached ({MAX_STAGED})")
                action.setEnabled(False)

        if self._staging.staged_events:
            menu.addSeparator()
            clear = menu.addAction(f"Clear all staged ({len(self._staging.staged_events)})")
            clear.triggered.connect(self._clear_staging)

        menu.exec(self._event_detail.mapToGlobal(pos))

    def _stage_event(self, event_name: str) -> None:
        if self._step15_active_data is None:
            return
        combo_df = self._step15_active_data.get("combo", pd.DataFrame())
        if self._staging.stage_event(event_name, combo_df):
            self._staging_bar.update_staging(self._staging.staged_events)
            if self.current_event:
                self._fill_observed_combos(self.current_event)

    def _unstage_event(self, event_name: str) -> None:
        if self._staging.unstage_event(event_name):
            self._staging_bar.update_staging(self._staging.staged_events)
            if self.current_event:
                self._fill_observed_combos(self.current_event)

    def _clear_staging(self) -> None:
        self._staging.clear_staging()
        self._staging_bar.update_staging([])
        if self.current_event:
            self._fill_observed_combos(self.current_event)

    # ------------------------------------------------------------------
    # 이미지 생성 연동
    # ------------------------------------------------------------------

    def _on_send_to_main(self) -> None:
        """현재 프롬프트를 파이프라인 경유로 메인 프롬프트에 전송."""
        prompt = self._prompt_edit.toPlainText().strip()
        if not prompt:
            return
        self.apply_to_main_prompt.emit({"general": prompt})

    def _on_send_and_generate(self) -> None:
        """메인 프롬프트에 파이프라인 경유 전송 + Event Preset 내 이미지 생성.

        on_generate_with_image_requested 패턴:
        1) apply_to_main_prompt → on_instant_generation_requested (풀 파이프라인)
        2) QTimer 100ms 후 execute_generation_pipeline (파이프라인 결과로 생성)
        """
        prompt = self._prompt_edit.toPlainText().strip()
        if not prompt:
            return
        if self._generating:
            return

        self._set_generating_state(True)

        # 1) 메인 프롬프트에 파이프라인 경유 전송 (풀 버전으로 업데이트)
        self.apply_to_main_prompt.emit({"general": prompt})

        # 2) UI 반영 후 이미지 생성 트리거
        QTimer.singleShot(100, self._trigger_send_and_generate)

    def _trigger_send_and_generate(self) -> None:
        """전송 완료 후 이미지 생성 트리거.

        on_generate_with_image_requested 패턴을 따름:
        - input override 없음 → step 1에서 파이프라인이 처리한 프롬프트 사용
        - event_preset_request + 해상도만 override
        """
        main_window = getattr(self.app_context, 'main_window', None)
        if not main_window:
            self._set_generating_state(False)
            return

        self.app_context.skip_prompt_engineering_auto_hide = True

        self.app_context.subscribe(
            "generation_completed_for_event_preset",
            self._on_send_gen_completed,
        )
        self.app_context.subscribe("generation_error", self._on_send_gen_error)

        override_params = {
            'event_preset_request': True,
            'width': 1024,
            'height': 1024,
        }
        main_window.generation_controller.execute_generation_pipeline(
            overrides=override_params,
        )

    def _on_send_gen_completed(self, result) -> None:
        self._unsubscribe_send_gen()
        if hasattr(result, 'mode'):
            self._image_preview.display_image(result)
        self._set_generating_state(False)

    def _on_send_gen_error(self, error_data: dict) -> None:
        if not error_data.get("event_preset_request"):
            return
        self._unsubscribe_send_gen()
        error_msg = error_data.get("message", "알 수 없는 오류")
        print(f"[EventPreset] 전송+생성 오류: {error_msg}")
        self._set_generating_state(False)
        QMessageBox.warning(self, "이미지 생성 실패", error_msg[:200])

    def _unsubscribe_send_gen(self) -> None:
        if not self.app_context:
            return
        for event_name, callback in [
            ("generation_completed_for_event_preset", self._on_send_gen_completed),
            ("generation_error", self._on_send_gen_error),
        ]:
            if event_name in self.app_context.subscribers:
                try:
                    self.app_context.subscribers[event_name].remove(callback)
                except ValueError:
                    pass

    def _on_generate_clicked(self) -> None:
        """Generate 클릭 → PromptProcessor 파이프라인 경유 → 이미지 생성."""
        if not self.app_context:
            print("[EventPreset] app_context 없음")
            return

        if self._generating:
            return

        main_window = getattr(self.app_context, 'main_window', None)
        if not main_window:
            print("[EventPreset] main_window 없음")
            return

        prompt = self._prompt_edit.toPlainText().strip()
        if not prompt:
            return

        try:
            self._set_generating_state(True)

            # 1) 메인 윈도우 settings 수집 (모듈 훅에 필요)
            settings = self._collect_main_settings(main_window)

            # 2) 프롬프트를 파이프라인에 통과 (silent — 메인 창 무변경)
            #    Auto Hide 스킵 (이벤트 프리셋 프롬프트에 불필요한 태그 제거 방지)
            self.app_context.skip_prompt_engineering_auto_hide = True
            tags_dict = {'general': prompt}
            processed = main_window.prompt_gen_controller.generate_instant_source_silent(
                tags_dict, settings,
            )
            final_prompt = processed or prompt  # 파이프라인 실패 시 원본 사용

            # 3) 처리된 프롬프트로 이미지 생성 요청 (해상도 1024x1024 고정)
            override_params = {
                'input': final_prompt,
                'event_preset_request': True,
                'width': 1024,
                'height': 1024,
            }

            self.app_context.subscribe(
                "generation_completed_for_event_preset",
                self._on_generation_completed,
            )
            self.app_context.subscribe("generation_error", self._on_generation_error)

            gen_controller = main_window.generation_controller
            gen_controller.execute_generation_pipeline(overrides=override_params)
            print(f"[EventPreset] 생성 시작 (pipeline): {final_prompt[:80]}...")

        except Exception as e:
            print(f"[EventPreset] 생성 오류: {e}")
            import traceback
            traceback.print_exc()
            self._set_generating_state(False)

    @staticmethod
    def _collect_main_settings(main_window) -> dict:
        """메인 윈도우에서 PromptProcessor에 필요한 settings 수집."""
        comfyui_sampling_mode = "eps"
        if hasattr(main_window, 'anima_radio') and main_window.anima_radio.isChecked():
            comfyui_sampling_mode = "anima"
        elif hasattr(main_window, 'v_pred_radio') and main_window.v_pred_radio.isChecked():
            comfyui_sampling_mode = "v_prediction"
        elif hasattr(main_window, 'eps_radio') and main_window.eps_radio.isChecked():
            comfyui_sampling_mode = "eps"

        cb = main_window.generation_checkboxes
        return {
            'prompt_fixed': cb["프롬프트 고정"].isChecked(),
            'auto_generate': False,  # Event Preset은 자동 생성 불필요
            'turbo_mode': cb["터보 옵션"].isChecked(),
            'wildcard_standalone': cb["와일드카드 단독 모드"].isChecked(),
            'api_mode': main_window.app_context.get_api_mode(),
            'comfyui_sampling_mode': comfyui_sampling_mode,
        }

    def _on_generation_completed(self, result) -> None:
        """생성 완료 콜백."""
        try:
            # 구독 해제
            self._unsubscribe_generation()

            if hasattr(result, 'mode'):  # PIL Image
                self._image_preview.display_image(result)
                print("[EventPreset] 이미지 생성 완료")
            else:
                print(f"[EventPreset] 예상과 다른 결과: {type(result)}")

            self._set_generating_state(False)
        except Exception as e:
            print(f"[EventPreset] 완료 처리 오류: {e}")
            import traceback
            traceback.print_exc()
            self._set_generating_state(False)

    def _on_generation_error(self, error_data: dict) -> None:
        """생성 에러 콜백."""
        if not error_data.get("event_preset_request"):
            return

        try:
            self._unsubscribe_generation()
            error_msg = error_data.get("message", "알 수 없는 오류")
            print(f"[EventPreset] 생성 오류: {error_msg}")
            self._set_generating_state(False)

            QMessageBox.warning(self, "이미지 생성 실패", error_msg[:200])
        except Exception as e:
            print(f"[EventPreset] 에러 처리 오류: {e}")
            self._set_generating_state(False)

    def _unsubscribe_generation(self) -> None:
        """생성 이벤트 구독 해제."""
        if not self.app_context:
            return
        for event_name, callback in [
            ("generation_completed_for_event_preset", self._on_generation_completed),
            ("generation_error", self._on_generation_error),
        ]:
            if event_name in self.app_context.subscribers:
                try:
                    self.app_context.subscribers[event_name].remove(callback)
                except ValueError:
                    pass

    def _set_generating_state(self, generating: bool) -> None:
        """Generate / 전송+즉시생성 버튼 상태 통합 제어."""
        self._generating = generating
        self._generate_btn.setEnabled(not generating)
        self._generate_btn.setText("Generating..." if generating else "Generate")
        self._send_and_gen_btn.setEnabled(not generating)

    # ------------------------------------------------------------------
    # 윈도우 닫기
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        self._unsubscribe_generation()
        self._unsubscribe_send_gen()
        self._data_manager.close()
        self.window_closed.emit()
        super().closeEvent(event)
