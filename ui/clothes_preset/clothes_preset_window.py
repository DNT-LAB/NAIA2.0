"""
Clothes Preset Window — NAIA 2.0 통합 메인 윈도우

viewer_clothes.py ClothesViewer를 NAIA 테마로 재작성.
3-Panel 레이아웃: Combo Catalog | 6-Slot Region Grid | Image+Prompt

변경 사항 (vs viewer_clothes.py):
- Send/Send+Generate 제거 → 클립보드 복사만
- LEFT 패널에 번역 패널 추가 (KR tags 쿼리)
- CENTER 검색에 한글→영어 지원
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QImage, QPixmap
from PyQt6.QtWidgets import QGraphicsOpacityEffect
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableView,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

from core.clothes_preset.data_manager import (
    PACKAGE_FILE_NAME,
    ClothesPresetDataManager,
    ComboSummary,
    RegionTag,
    fmt_k_count,
    norm_text,
    parse_csv_tags,
    unique_preserve,
)
from .download_worker import ClothesPresetDownloadDialog, ClothesPresetDownloadWorker
from core.clothes_preset.engines import (
    DISPLAY_SLOTS,
    MAX_COMBO_ROWS_DISPLAY,
    MAX_ROWS_PER_REGION,
    PAIR_MODE_PROFILES,
    REGIONS,
    SEARCH_DEBOUNCE_MS,
    SLOT_LABELS,
    ClothingTaxonomyEngine,
    EXPRESSION_GROUPS,
    PromptBuilder,
    RulesEngine,
    build_expression_group_tree,
    compute_promoted_tags,
)
from .widgets import (
    PINNED_ROLE, ComboHtmlDelegate, ComboTableModel,
    ExprTreeDelegate, FlowLayout, StagedTagChip,
)


# ---------------------------------------------------------------------------
# 데이터 경로
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parents[2] / "core" / "clothes_preset"
DATA_ZIP_PATH = DATA_DIR / PACKAGE_FILE_NAME
_EMPTY_FSET: frozenset[int] = frozenset()  # 호환성 필터용 빈 집합 센티널


# ---------------------------------------------------------------------------
# 메인 윈도우
# ---------------------------------------------------------------------------

class ClothesPresetWindow(QMainWindow):
    """Clothes Preset 메인 윈도우 — 의류 택소노미 브라우저."""

    window_closed = pyqtSignal()

    # ------------------------------------------------------------------
    # Static: 데이터 확인 + 다운로드
    # ------------------------------------------------------------------

    @staticmethod
    def ensure_data_available(parent=None) -> bool:
        """데이터 존재 확인. 없으면 다운로드 대화상자 표시."""
        dm = ClothesPresetDataManager()
        if dm.is_data_available():
            dm.close()
            return True
        dm.close()

        # TODO(web-dialog): 원래 QMessageBox(Yes/No) 다운로드 confirm + ClothesPresetDownloadDialog.exec() (worker sub-loop).
        # Web Shell 진행률 UI + confirm 모달로 재구현 필요. 안전 기본값 — 다운로드 차단.
        print("[Dialog/CONFIRM(skipped→No)] Clothes Preset 데이터 다운로드 confirm 차단 — Web Shell 재구현 예정")
        return False

    # ------------------------------------------------------------------
    # 생성자
    # ------------------------------------------------------------------

    def __init__(self, app_context=None, kr_tags_df=None, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._kr_tags_df = kr_tags_df if kr_tags_df is not None else pd.DataFrame()

        self.setWindowTitle("Clothes Preset")
        self.setMinimumSize(get_scaled_size(1800), get_scaled_size(980))
        self.resize(get_scaled_size(2200), get_scaled_size(1190))

        # 엔진
        self._taxonomy = ClothingTaxonomyEngine()

        # 데이터 상태
        self._combo_summaries: list[ComboSummary] = []
        self._combo_summaries_ge2: list[ComboSummary] = []
        self._combo_tag_to_ids: dict[str, set[int]] = {}
        self._filtered_combo_summaries: list[ComboSummary] = []
        self._combo_table_reloading = False
        self._combo_initialized_once = False

        self._region_tags: list[RegionTag] = []
        self._region_to_tags: dict[str, list[RegionTag]] = {r: [] for r in REGIONS}
        self._region_summary: dict[str, tuple[int, int]] = {r: (0, 0) for r in REGIONS}
        self._tag_to_region: dict[str, str] = {}

        self._assigned_slot_by_tag: dict[str, str] = {}
        self._assigned_group_by_tag: dict[str, str] = {}
        self._assigned_row_by_tag: dict[str, RegionTag] = {}
        self._slot_rows_cache: dict[str, list[RegionTag]] = {s: [] for s in DISPLAY_SLOTS}

        self._reco_by_seed: dict[str, list[dict[str, Any]]] = {}
        self._avoid_by_seed: dict[str, list[dict[str, Any]]] = {}
        self._pair_by_seed: dict[str, list[dict[str, Any]]] = {}
        self._conflict_pairs: set[tuple[str, str]] = set()
        self._conflict_exclusion_score: dict[tuple[str, str], float] = {}

        self._current_reco_agg: dict[str, dict[str, Any]] = {}
        self._current_avoid_agg: dict[str, dict[str, Any]] = {}
        self._current_pair_agg: dict[str, dict[str, Any]] = {}

        self._expr_by_combo: dict[str, list[dict[str, Any]]] = {}
        self._expr_global: list[dict[str, Any]] = []

        self._current_combo = ""
        self._combo_seed_tags: list[str] = []
        self._staged_tags: list[str] = []
        self._region_staged: dict[str, list[str]] = {s: [] for s in DISPLAY_SLOTS}
        self._promoted_set: set[str] = set()
        self._staged_expressions: list[str] = []
        self._pinned_expr_item: QTreeWidgetItem | None = None
        self._active_slot: str = DISPLAY_SLOTS[0]
        self._pair_mode = "Balanced"
        self._generating = False
        self._lucky_generating = False
        self._qimage_ref = None  # GC 방지
        self._prompt_plain_text = ""
        self._seed_region_counts: dict[str, int] = {r: 0 for r in REGIONS}

        # 한글→영어 검색 인덱스 (kr_tags_df 기반)
        self._kr_search_index: dict[str, set[str]] = {}
        self._kr_tag_cache: dict[str, tuple[str, str]] = {}  # tag → (category, desc)
        self._build_kr_search_index()
        self._build_kr_tag_cache()

        # UI 빌드
        self._build_ui()
        self._init_debounce_timers()
        self._apply_theme()

        # 자동화 중단 이벤트 구독 (자동 랜덤 체크 해제)
        if self.app_context:
            self.app_context.subscribe("automation_stopped", self._on_automation_stopped)

        # 데이터 로드 (deferred — 윈도우 먼저 표시 후 다음 이벤트 루프에서 로드)
        self._dm = ClothesPresetDataManager()
        self._data_loaded = False
        QTimer.singleShot(0, self._deferred_init)

    def _deferred_init(self) -> None:
        """윈도우 표시 후 데이터 로드 + 초기 갱신."""
        if self._data_loaded or not self.isVisible():
            return
        self._load_all()
        self._refresh_combo_candidates_from_stage()
        self._data_loaded = True

    # ------------------------------------------------------------------
    # 한글→영어 검색 인덱스
    # ------------------------------------------------------------------

    def _build_kr_search_index(self) -> None:
        """kr_tags_df의 desc/keywords 필드를 인덱싱하여 한글→영어 태그 매핑."""
        if self._kr_tags_df is None or self._kr_tags_df.empty:
            return
        for _, row in self._kr_tags_df.iterrows():
            tag = str(row.get("tag", ""))
            if not tag:
                continue
            tag_lower = tag.strip().lower()
            # desc 인덱싱
            desc = str(row.get("desc", ""))
            if pd.notna(desc) and desc:
                for word in desc.split():
                    word = word.strip().lower()
                    if word and len(word) >= 2:
                        self._kr_search_index.setdefault(word, set()).add(tag_lower)
            # keywords 인덱싱
            keywords = str(row.get("keywords", ""))
            if pd.notna(keywords) and keywords:
                for kw in keywords.split(","):
                    kw = kw.strip().lower()
                    if kw and len(kw) >= 2:
                        self._kr_search_index.setdefault(kw, set()).add(tag_lower)

    def _build_kr_tag_cache(self) -> None:
        """kr_tags_df → dict[tag, (category, desc)] 사전 구축 (O(1) 번역 조회용)."""
        if self._kr_tags_df is None or self._kr_tags_df.empty:
            return
        for _, row in self._kr_tags_df.iterrows():
            tag = str(row.get("tag", "")).strip()
            if not tag:
                continue
            cat = str(row.get("category", "")) if pd.notna(row.get("category")) else ""
            desc = str(row.get("desc", "")) if pd.notna(row.get("desc")) else ""
            self._kr_tag_cache[tag] = (cat, desc)

    def _kr_search(self, query: str) -> set[str]:
        """한글 쿼리로 영어 태그 집합을 반환."""
        query_lower = query.strip().lower()
        if not query_lower:
            return set()
        result: set[str] = set()
        for key, tags in self._kr_search_index.items():
            if query_lower in key:
                result.update(tags)
        return result

    # ------------------------------------------------------------------
    # UI 빌드
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(
            get_scaled_size(8), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8),
        )
        main_layout.setSpacing(get_scaled_size(6))

        # 고정 비율 3-Panel (1 : 2.4 : 1)
        splitter = QSplitter(Qt.Orientation.Horizontal, root)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(get_scaled_size(4))
        main_layout.addWidget(splitter, 1)
        self._main_splitter = splitter
        self._panel_ratio = (1.0, 2.4, 1.5)
        self._left_panel: QWidget | None = None  # _apply_panel_ratio에서 고정 너비 부여

        # ---- LEFT PANEL ----
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(get_scaled_size(4))

        # Top 행: 검색 + Pair 모드
        top_row = QHBoxLayout()
        self._combo_search = QLineEdit()
        self._combo_search.setPlaceholderText("Search combos...")
        self._combo_search.textChanged.connect(self._on_combo_search_changed)
        top_row.addWidget(self._combo_search, 1)

        self._pair_mode_combo = QComboBox()
        self._pair_mode_combo.addItems(list(PAIR_MODE_PROFILES.keys()))
        self._pair_mode_combo.setCurrentText(self._pair_mode)
        self._pair_mode_combo.currentTextChanged.connect(self._on_pair_mode_changed)
        self._pair_mode_combo.setFixedWidth(get_scaled_size(100))
        top_row.addWidget(self._pair_mode_combo)
        left_l.addLayout(top_row)

        count_row = QHBoxLayout()
        count_row.setSpacing(get_scaled_size(4))
        self._combo_count_label = QLabel("0 combos")
        count_row.addWidget(self._combo_count_label, 1)
        self._clear_all_btn = QPushButton("Clear All Staged")
        self._clear_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_all_btn.clicked.connect(self._clear_staging)
        count_row.addWidget(self._clear_all_btn)
        left_l.addLayout(count_row)

        # LEFT 내부 분할: Combo : Expression
        left_splitter = QSplitter(Qt.Orientation.Vertical)

        # Combo 테이블 (2컬럼: Observed Clothing Combo + Count, 줄넘김)
        self._combo_model = ComboTableModel()
        self._combo_table = QTableView()
        self._combo_table.setModel(self._combo_model)
        self._combo_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._combo_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._combo_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._combo_table.verticalHeader().setVisible(False)
        self._combo_table.setWordWrap(True)
        self._combo_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._combo_table.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        )
        self._combo_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        combo_header = self._combo_table.horizontalHeader()
        combo_header.setStretchLastSection(False)
        combo_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        combo_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._combo_table.setColumnWidth(1, get_scaled_size(55))
        self._combo_table.setItemDelegateForColumn(0, ComboHtmlDelegate(self._combo_table))
        self._combo_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._combo_table.customContextMenuRequested.connect(self._on_combo_context_menu)
        self._combo_table.selectionModel().currentRowChanged.connect(
            lambda _cur, _prev: self._on_combo_selected()
        )
        self._combo_table.doubleClicked.connect(self._on_combo_double_clicked)
        left_splitter.addWidget(self._combo_table)

        # Expression 트리 (그룹별)
        expr_widget = QWidget()
        expr_l = QVBoxLayout(expr_widget)
        expr_l.setContentsMargins(0, 0, 0, 0)
        expr_l.setSpacing(get_scaled_size(2))
        self._expr_count_label = QLabel("0 expression sets")
        expr_l.addWidget(self._expr_count_label)
        self._expr_tree = QTreeWidget()
        self._expr_tree.setObjectName("exprTree")
        self._expr_tree.setColumnCount(1)
        self._expr_tree.setHeaderHidden(True)
        self._expr_tree.setRootIsDecorated(True)
        self._expr_tree.setIndentation(get_scaled_size(16))
        self._expr_tree.setUniformRowHeights(True)
        self._expr_tree.setAlternatingRowColors(False)
        self._expr_tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self._expr_tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._expr_tree.header().setStretchLastSection(True)
        self._expr_tree.setItemDelegate(ExprTreeDelegate(self._expr_tree))
        self._expr_tree.itemClicked.connect(self._on_expr_tree_clicked)
        expr_l.addWidget(self._expr_tree)
        left_splitter.addWidget(expr_widget)

        left_splitter.setStretchFactor(0, 3)   # Combo
        left_splitter.setStretchFactor(1, 2)   # Expression
        left_l.addWidget(left_splitter, 1)

        # ---- CENTER PANEL ----
        center = QWidget()
        center_l = QVBoxLayout(center)
        center_l.setContentsMargins(0, 0, 0, 0)
        center_l.setSpacing(get_scaled_size(4))

        # 상단 바: 좌=검색+Clear, 우=번역 2줄 (비율 1:4)
        top_bar = QHBoxLayout()
        top_bar.setSpacing(get_scaled_size(8))

        # 좌측: 검색 + Clear (세로 배치)
        search_box = QVBoxLayout()
        search_box.setSpacing(get_scaled_size(3))
        self._region_search = QLineEdit()
        self._region_search.setPlaceholderText("Search tags...")
        self._region_search.textChanged.connect(self._on_region_search_changed)
        search_box.addWidget(self._region_search)
        self._region_search_clear_btn = QPushButton("Clear")
        self._region_search_clear_btn.setObjectName("searchClearBtn")
        self._region_search_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._region_search_clear_btn.clicked.connect(lambda: self._region_search.clear())
        search_box.addWidget(self._region_search_clear_btn)
        top_bar.addLayout(search_box, 1)

        # 우측: 번역 패널 (단일 고정 높이 RichText 라벨)
        self._info_label = QLabel()
        self._info_label.setObjectName("infoLabel")
        self._info_label.setTextFormat(Qt.TextFormat.RichText)
        self._info_label.setWordWrap(True)
        self._info_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        h = get_scaled_size(52)
        self._info_label.setFixedHeight(h)
        self._hide_info_labels()  # 플레이스홀더
        top_bar.addWidget(self._info_label, 4)

        center_l.addLayout(top_bar)

        # 6-Slot Grid (2행 × 3열)
        grid = QGridLayout()
        grid.setSpacing(get_scaled_size(4))
        self._region_trees: dict[str, QTreeWidget] = {}
        self._region_count_labels: dict[str, QLabel] = {}
        self._slot_chip_layouts: dict[str, FlowLayout] = {}
        self._slot_chip_containers: dict[str, QWidget] = {}
        self._slot_clear_btns: dict[str, QPushButton] = {}

        # 슬롯별 테두리 색상 (뮤트 파스텔 — 다크 테마 조화)
        self._slot_accent_colors = _SLOT_ACCENT = {
            "HEAD_NECK_FACE": "#C4796A",   # coral
            "UPPER_BODY":    "#6A9EC4",    # sky blue
            "WAIST_HIP":     "#6AC48A",    # green
            "ARMS_HANDS":    "#9B7BC4",    # lavender
            "LEGS_FEET":     "#C4AB6A",    # amber
            "STYLE":         "#C46A9B",    # rose
        }

        for idx, slot in enumerate(DISPLAY_SLOTS):
            row_idx = idx // 3
            col_idx = idx % 3
            slot_color = _SLOT_ACCENT.get(slot, DARK_COLORS['border'])

            slot_box = QVBoxLayout()
            slot_box.setSpacing(get_scaled_size(2))

            # 타이틀 (슬롯 색상 적용)
            title = QLabel(SLOT_LABELS.get(slot, slot))
            title.setStyleSheet(
                f"color: {slot_color}; font-weight: bold; border: none;"
            )
            slot_box.addWidget(title)

            # 카운트
            count_lbl = QLabel("0 rows")
            self._region_count_labels[slot] = count_lbl
            slot_box.addWidget(count_lbl)

            # 트리 (단일 컬럼 — count 인라인 표시)
            tree = QTreeWidget()
            tree.setColumnCount(1)
            tree.setHeaderHidden(True)
            tree.setRootIsDecorated(True)
            tree.setIndentation(get_scaled_size(16))
            tree.setUniformRowHeights(True)
            tree.setAlternatingRowColors(False)
            tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
            tree.header().setStretchLastSection(True)
            tree.itemDoubleClicked.connect(
                lambda item, _col, s=slot: self._on_tree_item_double_clicked(s, item)
            )
            tree.itemClicked.connect(
                lambda item, _col, s=slot: self._on_tree_item_clicked(s, item)
            )
            tree.itemSelectionChanged.connect(
                lambda s=slot: self._set_active_slot(s)
            )
            # 슬롯별 트리 테두리 색상
            tree.setStyleSheet(f"""
                QTreeWidget {{
                    border: 1px solid {slot_color};
                    border-top: 2px solid {slot_color};
                }}
            """)
            self._region_trees[slot] = tree
            slot_box.addWidget(tree, 1)

            # Staged 칩 영역 (고정 높이 패널 + Clear 버튼)
            stage_panel = QWidget()
            stage_panel.setObjectName("stagePanel")
            stage_panel.setStyleSheet(f"""
                QWidget#stagePanel {{
                    background-color: #2B2B2B;
                    border: 1px solid {DARK_COLORS['border']};
                    border-radius: {get_scaled_size(3)}px;
                }}
            """)
            stage_panel.setMinimumHeight(get_scaled_size(52))
            stage_panel_l = QVBoxLayout(stage_panel)
            stage_panel_l.setContentsMargins(
                get_scaled_size(4), get_scaled_size(2),
                get_scaled_size(4), get_scaled_size(2),
            )
            stage_panel_l.setSpacing(get_scaled_size(2))

            # Clear 버튼 (우상단 정렬)
            clear_row = QHBoxLayout()
            clear_row.setContentsMargins(0, 0, 0, 0)
            clear_row.addStretch(1)
            clear_btn = QPushButton("Clear")
            clear_btn.setObjectName("slotClearBtn")
            clear_btn.setFixedHeight(get_scaled_size(18))
            clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            clear_btn.clicked.connect(lambda checked=False, s=slot: self._on_slot_clear(s))
            clear_btn.setVisible(False)
            self._slot_clear_btns[slot] = clear_btn
            clear_row.addWidget(clear_btn)
            stage_panel_l.addLayout(clear_row)

            # 칩 FlowLayout
            chip_container = QWidget()
            chip_container.setStyleSheet("background: transparent; border: none;")
            chip_flow = FlowLayout(chip_container, spacing=get_scaled_size(3))
            chip_flow.setContentsMargins(0, 0, 0, 0)
            self._slot_chip_layouts[slot] = chip_flow
            self._slot_chip_containers[slot] = chip_container
            stage_panel_l.addWidget(chip_container, 1)

            slot_box.addWidget(stage_panel)

            grid.addLayout(slot_box, row_idx, col_idx)

        center_l.addLayout(grid, 1)

        # ---- RIGHT PANEL ----
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(
            get_scaled_size(4), get_scaled_size(8),
            get_scaled_size(8), get_scaled_size(8),
        )
        right_l.setSpacing(get_scaled_size(6))

        # 이미지 프리뷰 (832:1216 비율 고정)
        self._image_preview = QLabel()
        self._image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_preview.setMinimumSize(get_scaled_size(280), get_scaled_size(410))
        self._image_preview.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )
        self._image_preview.setText("832 × 1216")
        right_l.addWidget(self._image_preview, stretch=1)

        # Generate + I Feel Lucky 버튼 행
        gen_row = QHBoxLayout()
        gen_row.setSpacing(get_scaled_size(6))

        self._generate_btn = QPushButton("Generate")
        self._generate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._generate_btn.clicked.connect(self._on_generate_clicked)
        gen_row.addWidget(self._generate_btn, stretch=3)

        self._lucky_btn = QPushButton("I Feel Lucky")
        self._lucky_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._lucky_btn.clicked.connect(self._on_lucky_clicked)
        gen_row.addWidget(self._lucky_btn, stretch=2)

        right_l.addLayout(gen_row)

        # 프롬프트 + 자동 랜덤 + Rating 체크박스
        prompt_row = QHBoxLayout()
        prompt_row.setSpacing(get_scaled_size(6))
        prompt_label = QLabel("Prompt")
        prompt_row.addWidget(prompt_label)

        # 자동 랜덤 체크박스 (I Feel Lucky 후 노출, Prompt 옆)
        self._auto_random_cb = QCheckBox("자동 랜덤")
        self._auto_random_cb.setStyleSheet(f"""
            QCheckBox {{
                color: #FFB0C8;
                font-size: {get_scaled_font_size(13)}px;
            }}
            QCheckBox::indicator {{
                width: {get_scaled_size(14)}px;
                height: {get_scaled_size(14)}px;
            }}
        """)
        self._auto_random_cb.setVisible(False)
        self._auto_random_opacity = QGraphicsOpacityEffect(self._auto_random_cb)
        self._auto_random_opacity.setOpacity(1.0)
        self._auto_random_cb.setGraphicsEffect(self._auto_random_opacity)
        self._auto_random_fade_anim: QPropertyAnimation | None = None
        self._auto_random_fade_timer = QTimer(self)
        self._auto_random_fade_timer.setSingleShot(True)
        self._auto_random_fade_timer.timeout.connect(self._start_auto_random_fade)
        self._auto_random_cb.toggled.connect(self._on_auto_random_toggled)
        prompt_row.addWidget(self._auto_random_cb)

        prompt_row.addStretch(1)

        from PyQt6.QtWidgets import QButtonGroup
        self._rating_checkboxes: dict[str, QCheckBox] = {}
        self._rating_group = QButtonGroup(self)
        self._rating_group.setExclusive(True)
        for rating_name in ("general", "sensitive", "questionable", "explicit"):
            cb = QCheckBox(rating_name)
            cb.setChecked(rating_name == "sensitive")
            self._rating_group.addButton(cb)
            cb.toggled.connect(lambda checked, name=rating_name: self._on_rating_toggled(name, checked))
            prompt_row.addWidget(cb)
            self._rating_checkboxes[rating_name] = cb
        right_l.addLayout(prompt_row)
        self._prompt_edit = QTextEdit()
        self._prompt_edit.setAcceptRichText(True)
        self._prompt_edit.setPlaceholderText("Prompt preview based on current staged tags")
        self._prompt_edit.setMaximumHeight(get_scaled_size(120))
        right_l.addWidget(self._prompt_edit)

        # 유틸 행: [Copy to Clipboard]
        self._copy_btn = QPushButton("Copy to Clipboard")
        self._copy_btn.clicked.connect(self._on_copy_to_clipboard)
        right_l.addWidget(self._copy_btn)

        # 스플리터에 패널 추가 + 핸들 드래그 비활성
        self._left_panel = left
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        for i in range(1, splitter.count()):
            handle = splitter.handle(i)
            if handle:
                handle.setEnabled(False)
        self._apply_panel_ratio()

    def _apply_theme(self) -> None:
        """NAIA 다크 테마 적용."""
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
                font-size: {fs(15)}px;
                padding: {ss(4)}px {ss(6)}px;
            }}
            QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                font-size: {fs(17)}px;
            }}
            QLabel {{
                color: {DARK_COLORS['text_primary']};
                border: none;
                font-size: {fs(17)}px;
            }}
            QLineEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {ss(3)}px;
                padding: {ss(4)}px {ss(8)}px;
                font-size: {fs(16)}px;
            }}
            QComboBox {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {ss(3)}px;
                padding: {ss(4)}px {ss(8)}px;
                font-size: {fs(17)}px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                selection-background-color: {DARK_COLORS['accent_blue']};
                font-size: {fs(17)}px;
            }}
            QTableView, QTableWidget {{
                background-color: #1A1A1A;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                gridline-color: {DARK_COLORS['border']};
                font-size: {fs(19)}px;
                alternate-background-color: #1E1E1E;
            }}
            QTableView::item:selected, QTableWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
                color: #FFFFFF;
            }}
            QHeaderView::section {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                padding: {ss(4)}px;
                font-size: {fs(14)}px;
            }}
            QTreeWidget {{
                background-color: #212121;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                font-size: {fs(17)}px;
            }}
            QTreeWidget::item {{
                padding: {ss(2)}px 0px;
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
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {ss(3)}px;
                padding: {ss(6)}px;
                font-size: {fs(20)}px;
            }}
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {ss(4)}px;
                padding: {ss(6)}px {ss(12)}px;
                font-size: {fs(14)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_secondary']};
            }}
            QSplitter::handle {{
                background-color: {DARK_COLORS['border']};
                width: 1px;
            }}
            QPushButton#slotClearBtn {{
                background-color: transparent;
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {ss(2)}px;
                padding: 0px {ss(6)}px;
                font-size: {fs(11)}px;
            }}
            QPushButton#slotClearBtn:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        # 이미지 프리뷰 스타일
        self._image_preview.setStyleSheet(f"""
            QLabel {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                color: {DARK_COLORS['text_disabled']};
                font-size: {fs(19)}px;
            }}
        """)

        # 카운트 라벨 스타일
        secondary_lbl_style = f"color: {DARK_COLORS['text_secondary']}; font-size: {fs(15)}px; border: none;"
        self._combo_count_label.setStyleSheet(secondary_lbl_style)
        self._expr_count_label.setStyleSheet(secondary_lbl_style)
        for lbl in self._region_count_labels.values():
            lbl.setStyleSheet(secondary_lbl_style)

        # 번역 패널 스타일 (흰색 배경, 고정 높이)
        self._info_label.setStyleSheet(
            f"QLabel#infoLabel {{"
            f"  background-color: #F5F5F5;"
            f"  border: 1px solid {DARK_COLORS['border']};"
            f"  border-radius: {ss(3)}px;"
            f"  padding: {ss(3)}px {ss(6)}px;"
            f"  color: #1A1A1A;"
            f"}}"
        )

        # 검색 Clear 버튼
        self._region_search_clear_btn.setStyleSheet(f"""
            QPushButton#searchClearBtn {{
                background-color: transparent;
                color: {DARK_COLORS['text_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {ss(3)}px;
                font-size: {fs(12)}px;
                padding: {ss(2)}px {ss(4)}px;
            }}
            QPushButton#searchClearBtn:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        # Generate 버튼
        self._generate_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                padding: {ss(6)}px {ss(12)}px;
                border-radius: {ss(4)}px;
                font-size: {fs(14)}px;
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

        # I Feel Lucky 버튼 (보라색)
        self._lucky_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #7B2FBE;
                color: white;
                padding: {ss(6)}px {ss(12)}px;
                border-radius: {ss(4)}px;
                font-size: {fs(14)}px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: #9B4FDE;
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_disabled']};
            }}
        """)

    # ------------------------------------------------------------------
    # 패널 비율 고정
    # ------------------------------------------------------------------

    def _apply_panel_ratio(self) -> None:
        """1:2.4:1.5 비율로 스플리터 크기 고정.

        LEFT 패널은 setFixedWidth로 강제 고정하여 테이블 컨텐츠 변경 시
        minimumSizeHint가 비율을 무너뜨리지 못하도록 한다.
        """
        sp = self._main_splitter
        available = sp.width() - sp.handleWidth() * (sp.count() - 1)
        if available <= 0:
            return
        r = self._panel_ratio
        total = sum(r)
        sizes = [int(available * v / total) for v in r]
        sizes[-1] = available - sum(sizes[:-1])  # 나머지 보정
        sp.setSizes(sizes)
        # LEFT 패널 너비를 직접 고정 — QSplitter가 컨텐츠 hint에 의해 밀리는 것을 방지
        if self._left_panel is not None:
            self._left_panel.setFixedWidth(sizes[0])

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_panel_ratio()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._apply_panel_ratio()

    # ------------------------------------------------------------------
    # 디바운스 타이머
    # ------------------------------------------------------------------

    def _init_debounce_timers(self) -> None:
        self._combo_search_timer = QTimer(self)
        self._combo_search_timer.setSingleShot(True)
        self._combo_search_timer.setInterval(350)
        self._combo_search_timer.timeout.connect(self._do_combo_search)

        self._region_search_timer = QTimer(self)
        self._region_search_timer.setSingleShot(True)
        self._region_search_timer.setInterval(350)
        self._region_search_timer.timeout.connect(self._refresh_region_tables)

    def _on_combo_search_changed(self, _text: str) -> None:
        self._combo_search_timer.start()

    def _do_combo_search(self) -> None:
        """디바운스 후 실제 콤보 검색 실행. 2글자 미만이면 무시."""
        needle = self._combo_search.text().strip()
        if needle and len(needle) < 2:
            return
        self._refresh_combo_candidates_from_stage()

    def _on_region_search_changed(self, _text: str) -> None:
        self._region_search_timer.start()

    # ------------------------------------------------------------------
    # 데이터 로딩
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        payload = self._dm.load_all()

        self._combo_summaries = payload.get("combo_summaries", [])
        self._combo_summaries_ge2 = payload.get("combo_summaries_ge2", [])
        self._combo_tag_to_ids = payload.get("combo_tag_to_ids", {})

        self._region_tags = payload.get("region_tags", [])
        self._region_to_tags = payload.get("region_to_tags", {r: [] for r in REGIONS})
        self._region_summary = payload.get("region_summary", {r: (0, 0) for r in REGIONS})
        self._tag_to_region = payload.get("tag_to_region", {})

        self._reco_by_seed = payload.get("reco_by_seed", {})
        self._avoid_by_seed = payload.get("avoid_by_seed", {})
        self._pair_by_seed = payload.get("pair_by_seed", {})
        self._conflict_pairs = payload.get("conflict_pairs", set())
        self._conflict_exclusion_score = payload.get("conflict_exclusion_score", {})

        self._expr_by_combo = payload.get("expr_by_combo", {})
        self._expr_global = payload.get("expr_global", [])

        # 슬롯 할당
        if payload.get("assigned_slot_by_tag"):
            self._assigned_slot_by_tag = payload["assigned_slot_by_tag"]
            self._assigned_group_by_tag = payload["assigned_group_by_tag"]
            self._assigned_row_by_tag = payload["assigned_row_by_tag"]
            self._slot_rows_cache = payload["slot_rows_cache"]
        else:
            result = self._taxonomy.rebuild_slot_assignment(self._region_tags)
            self._assigned_slot_by_tag = result["assigned_slot_by_tag"]
            self._assigned_group_by_tag = result["assigned_group_by_tag"]
            self._assigned_row_by_tag = result["assigned_row_by_tag"]
            self._slot_rows_cache = result["slot_rows_cache"]

        # 초기 갱신
        self._refresh_rules()
        self._refresh_seed_regions()
        self._refresh_region_tables()
        self._refresh_expected_expressions()

    # ------------------------------------------------------------------
    # 콤보 테이블 필터링
    # ------------------------------------------------------------------

    def _refresh_combo_candidates_from_stage(self) -> None:
        keyword = self._combo_search.text().strip().lower()
        staged = [t for t in self._staged_tags if t]
        staged_sig = tuple(sorted(set(staged))) if staged else ()
        selected_combo = ""
        cur_row = self._combo_table.currentIndex().row()
        if 0 <= cur_row < len(self._filtered_combo_summaries):
            selected_combo = self._filtered_combo_summaries[cur_row].clothing_combo

        hidden_exact = 0
        rows: list[ComboSummary] = []
        base_count = 0

        if staged:
            sets = [self._combo_tag_to_ids.get(t, set()) for t in staged]
            if not sets or any(len(s) == 0 for s in sets):
                ids: list[int] = []
            else:
                sets.sort(key=len)
                id_set = set(sets[0])
                for s in sets[1:]:
                    id_set.intersection_update(s)
                    if not id_set:
                        break
                ids = sorted(id_set)
            min_tags = max(2, len(staged))
            for idx in ids:
                c = self._combo_summaries[idx]
                if c.tag_count < min_tags:
                    continue
                if staged_sig and c.tags == staged_sig:
                    hidden_exact += 1
                    continue
                if keyword and keyword not in c.clothing_combo:
                    continue
                base_count += 1
                if len(rows) < MAX_COMBO_ROWS_DISPLAY:
                    rows.append(c)
        else:
            if not keyword:
                rows = self._combo_summaries_ge2[:MAX_COMBO_ROWS_DISPLAY]
                base_count = len(self._combo_summaries_ge2)
            else:
                for c in self._combo_summaries_ge2:
                    if keyword not in c.clothing_combo:
                        continue
                    base_count += 1
                    if len(rows) < MAX_COMBO_ROWS_DISPLAY:
                        rows.append(c)

        self._filtered_combo_summaries = rows
        self._combo_table_reloading = True
        self._combo_model.replace(self._filtered_combo_summaries)
        self._combo_table.scrollToTop()
        self._combo_table_reloading = False

        shown = len(self._filtered_combo_summaries)
        if staged:
            suffix = f" (match staged, exact hidden={hidden_exact:,})" if hidden_exact else " (match staged)"
            self._combo_count_label.setText(f"{shown:,} / {base_count:,} observed combos{suffix}")
        else:
            self._combo_count_label.setText(f"{shown:,} / {base_count:,} observed combos")

        if selected_combo:
            for i, c in enumerate(self._filtered_combo_summaries):
                if c.clothing_combo == selected_combo:
                    self._combo_table.selectRow(i)
                    return
        if not self._combo_initialized_once and self._filtered_combo_summaries:
            self._combo_initialized_once = True
            self._combo_table.selectRow(0)

    # ------------------------------------------------------------------
    # 콤보 선택 / 스테이징
    # ------------------------------------------------------------------

    def _on_combo_selected(self) -> None:
        if self._combo_table_reloading:
            return
        row = self._combo_table.currentIndex().row()
        if row < 0 or row >= len(self._filtered_combo_summaries):
            return
        summary = self._filtered_combo_summaries[row]
        self._current_combo = summary.clothing_combo
        self._combo_seed_tags = list(summary.tags)
        self._refresh_staging()
        self._refresh_translation_panel()

    def _on_combo_context_menu(self, pos) -> None:
        row = self._combo_table.indexAt(pos).row()
        if row < 0 or row >= len(self._filtered_combo_summaries):
            return
        self._combo_table.selectRow(row)
        summary = self._filtered_combo_summaries[row]
        menu = QMenu(self)
        add_action = menu.addAction(f"Stage Combo Tags ({len(summary.tags)})")
        action = menu.exec(self._combo_table.viewport().mapToGlobal(pos))
        if action == add_action:
            self._stage_combo_tags(summary.tags)

    def _on_combo_double_clicked(self, index) -> None:
        row = index.row()
        if row < 0 or row >= len(self._filtered_combo_summaries):
            return
        summary = self._filtered_combo_summaries[row]
        self._stage_combo_tags(summary.tags)

    def _stage_combo_tags(self, tags: tuple[str, ...]) -> None:
        if not tags or not self._data_loaded:
            return
        all_region = self._all_region_staged_tags()
        region_lookup = {r.tag: r for r in self._region_tags}
        added = False
        for t in tags:
            if not t or t in all_region:
                continue
            slot = self._slot_for_tag(t, region_lookup)
            if not slot:
                slot = "STYLE"
            self._region_staged.setdefault(slot, []).append(t)
            all_region.add(t)
            added = True
        if added:
            self._refresh_all_from_staging()

    # ------------------------------------------------------------------
    # 리전 트리 인터랙션
    # ------------------------------------------------------------------

    def _set_active_slot(self, slot: str) -> None:
        self._active_slot = slot

    def _on_tree_item_clicked(self, slot: str, item: QTreeWidgetItem) -> None:
        self._set_active_slot(slot)
        if item.parent() is None:
            item.setExpanded(not item.isExpanded())
            return
        # 자식 아이템 클릭 → 번역 정보 표시
        tag = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(tag, str) and tag.strip():
            self._update_tag_info(tag.strip())

    def _on_tree_item_double_clicked(self, slot: str, item: QTreeWidgetItem) -> None:
        self._set_active_slot(slot)
        if item.parent() is None:
            item.setExpanded(not item.isExpanded())
            return
        self._add_selected_region_tag(slot)

    def _selected_region_tag(self, slot: str | None = None) -> str:
        use_slot = slot or self._active_slot
        tree = self._region_trees.get(use_slot)
        if tree is None:
            return ""
        item = tree.currentItem()
        if item is None or item.parent() is None:
            return ""
        tag = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(tag, str) and tag.strip():
            return tag.strip()
        return item.text(0).strip()

    def _all_region_staged_tags(self) -> set[str]:
        """_region_staged 전체 태그 집합 (중복 체크용)."""
        result: set[str] = set()
        for tags in self._region_staged.values():
            result.update(tags)
        return result

    def _add_selected_region_tag(self, slot: str | None = None) -> None:
        if not self._data_loaded:
            return
        use_slot = slot or self._active_slot
        tag = self._selected_region_tag(use_slot)
        if not tag or tag in self._all_region_staged_tags():
            return
        self._region_staged.setdefault(use_slot, []).append(tag)
        self._refresh_all_from_staging()

    def _clear_staging(self) -> None:
        self._staged_tags = []
        self._region_staged = {s: [] for s in DISPLAY_SLOTS}
        self._promoted_set = set()
        self._staged_expressions = []
        self._pinned_expr_item = None
        self._reset_expr_tree_styles()
        self._refresh_all_from_staging()

    def _reset_expr_tree_styles(self) -> None:
        """Expression 트리의 모든 고정 스타일 초기화."""
        for i in range(self._expr_tree.topLevelItemCount()):
            parent = self._expr_tree.topLevelItem(i)
            if parent is None:
                continue
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child is not None:
                    self._update_expr_item_style(child, False)

    # ------------------------------------------------------------------
    # Pair 모드
    # ------------------------------------------------------------------

    def _on_pair_mode_changed(self, mode: str) -> None:
        if mode not in PAIR_MODE_PROFILES:
            return
        self._pair_mode = mode
        self._refresh_all_from_staging()

    # ------------------------------------------------------------------
    # promoted 재계산
    # ------------------------------------------------------------------

    def _recompute_staged_tags(self) -> None:
        """_region_staged → _promoted_set / _staged_tags 재계산."""
        self._promoted_set = compute_promoted_tags(
            self._region_staged,
            self._assigned_row_by_tag,
            self._assigned_group_by_tag,
        )
        # promoted 태그만 flat list 로 (DISPLAY_SLOTS 순서, 삽입 순서 유지)
        seen: set[str] = set()
        result: list[str] = []
        for slot in DISPLAY_SLOTS:
            for tag in self._region_staged.get(slot, []):
                if tag in self._promoted_set and tag not in seen:
                    seen.add(tag)
                    result.append(tag)
        self._staged_tags = result
        # 콤보 테이블 하이라이트 갱신
        self._combo_model.set_promoted(self._promoted_set)

    # ------------------------------------------------------------------
    # 갱신 캐스케이드
    # ------------------------------------------------------------------

    def _refresh_all_from_staging(self) -> None:
        self._combo_search_timer.stop()
        self._region_search_timer.stop()
        self._recompute_staged_tags()
        self._refresh_staging()
        self._refresh_rules()
        self._refresh_seed_regions()
        self._refresh_region_tables()
        self._refresh_combo_candidates_from_stage()

    def _refresh_staging(self) -> None:
        self._refresh_slot_stage_labels()
        self._rebuild_prompt_preview()
        self._refresh_translation_panel()

    def _refresh_rules(self) -> None:
        self._current_reco_agg, self._current_avoid_agg, self._current_pair_agg = (
            RulesEngine.refresh_rules(
                self._staged_tags,
                self._reco_by_seed,
                self._avoid_by_seed,
                self._pair_by_seed,
                self._pair_mode,
            )
        )

    def _refresh_seed_regions(self) -> None:
        self._seed_region_counts = {r: 0 for r in REGIONS}
        for t in self._staged_tags:
            rg = self._tag_to_region.get(t, "")
            if rg in self._seed_region_counts:
                self._seed_region_counts[rg] += 1

    # ------------------------------------------------------------------
    # 슬롯 Stage 라벨
    # ------------------------------------------------------------------

    def _slot_for_tag(self, tag: str, region_lookup: dict[str, RegionTag]) -> str:
        slot = self._assigned_slot_by_tag.get(tag, "")
        if slot:
            return slot
        rr = region_lookup.get(tag)
        if rr is None:
            return ""
        region = rr.region
        if region in {"LEGS", "FEET"}:
            return "LEGS_FEET"
        if region in DISPLAY_SLOTS:
            return region
        return ""

    def _refresh_slot_stage_labels(self) -> None:
        for slot in DISPLAY_SLOTS:
            flow = self._slot_chip_layouts.get(slot)
            if flow is None:
                continue
            flow.clear_widgets()
            tags = self._region_staged.get(slot, [])
            slot_color = self._slot_accent_colors.get(slot, "")
            for tag in tags:
                text_color = "#F5E6A3" if tag in self._promoted_set else ""
                chip = StagedTagChip(tag, border_color=slot_color, text_color=text_color)
                tip = self._make_tag_tooltip(tag)
                if tip:
                    chip.setToolTip(tip)
                chip.tag_clicked.connect(self._on_chip_tag_clicked)
                chip.remove_clicked.connect(self._on_chip_remove_clicked)
                flow.addWidget(chip)
            # Clear 버튼 표시/숨김
            clear_btn = self._slot_clear_btns.get(slot)
            if clear_btn is not None:
                clear_btn.setVisible(len(tags) > 0)

    def _on_chip_tag_clicked(self, tag: str) -> None:
        """칩 클릭 → 해당 태그의 번역 정보를 번역 패널에 표시."""
        self._show_translation_for_tags([tag])

    def _on_chip_remove_clicked(self, tag: str) -> None:
        """칩 × 클릭 → region_staged에서 태그 제거."""
        for slot_tags in self._region_staged.values():
            if tag in slot_tags:
                slot_tags.remove(tag)
                break
        self._refresh_all_from_staging()

    def _on_slot_clear(self, slot: str) -> None:
        """해당 슬롯의 region_staged 태그 전부 제거."""
        if not self._region_staged.get(slot):
            return
        self._region_staged[slot] = []
        self._refresh_all_from_staging()

    def _show_translation_for_tags(self, tags: list[str]) -> None:
        """특정 태그의 번역 정보를 번역 패널에 표시 (단일 태그 기준)."""
        self._hide_info_labels()
        if not tags:
            return
        tag = tags[0]
        self._update_tag_info(tag)

    # ------------------------------------------------------------------
    # 리전 테이블 갱신
    # ------------------------------------------------------------------

    def _tag_signal(self, tag: str) -> tuple[float, float, int, int]:
        reco_score = float(self._current_reco_agg.get(tag, {}).get("score", 0.0))
        pair_conf = float(self._current_pair_agg.get(tag, {}).get("max_conf", 0.0))
        pair_hits = int(self._current_pair_agg.get(tag, {}).get("hits", 0))
        pair_count = int(self._current_pair_agg.get(tag, {}).get("max_pair", 0))
        return reco_score, pair_conf, pair_hits, pair_count

    def _refresh_region_tables(self) -> None:
        keyword = self._region_search.text().strip().lower()
        staged_promoted = set(self._staged_tags)
        all_region_tags = self._all_region_staged_tags()
        candidate_set: set[str] = set(all_region_tags)

        # 한글 검색 지원
        kr_matched_tags: set[str] = set()
        if keyword:
            kr_matched_tags = self._kr_search(keyword)

        if staged_promoted:
            candidate_set.update(self._current_reco_agg.keys())
            candidate_set.update(self._current_pair_agg.keys())

        for slot in DISPLAY_SLOTS:
            tree = self._region_trees[slot]
            # 확장 상태 저장
            expanded_subgroups: set[str] = set()
            for i in range(tree.topLevelItemCount()):
                top = tree.topLevelItem(i)
                if top and top.isExpanded():
                    sg_key = top.data(0, Qt.ItemDataRole.UserRole + 1)
                    if isinstance(sg_key, str) and sg_key:
                        expanded_subgroups.add(sg_key)

            all_rows = list(self._slot_rows_cache.get(slot, []))
            rows = list(all_rows)
            if staged_promoted:
                rows = [r for r in rows if r.tag in candidate_set]
            # 모든 region_staged 태그를 트리에서 숨김
            rows = [r for r in rows if r.tag not in all_region_tags]

            # 리전 호환성 필터: 슬롯 내 staged 태그와 combo 교집합이 0이 되는 태그 숨김
            slot_tags = self._region_staged.get(slot, [])
            if slot_tags:
                slot_combo_ids: set[int] | None = None
                for st in slot_tags:
                    tag_ids = self._combo_tag_to_ids.get(st)
                    if tag_ids is None:
                        slot_combo_ids = set()
                        break
                    if slot_combo_ids is None:
                        slot_combo_ids = set(tag_ids)
                    else:
                        slot_combo_ids &= tag_ids
                        if not slot_combo_ids:
                            break
                if slot_combo_ids:
                    _ctid = self._combo_tag_to_ids
                    rows = [
                        r for r in rows
                        if not _ctid.get(r.tag, _EMPTY_FSET).isdisjoint(slot_combo_ids)
                    ]
                else:
                    rows = []

            if keyword:
                rows = [
                    r for r in rows
                    if keyword in r.tag
                    or keyword in r.subgroup
                    or keyword in r.reason
                    or keyword in self._assigned_group_by_tag.get(r.tag, "")
                    or r.tag in kr_matched_tags
                ]

            signal_cache: dict[str, tuple[float, float, int, int]] = {}
            for r in rows:
                if r.tag not in signal_cache:
                    signal_cache[r.tag] = self._tag_signal(r.tag)

            rows.sort(
                key=lambda r: (
                    0 if r.tag in all_region_tags else 1,
                    -signal_cache[r.tag][0],
                    -signal_cache[r.tag][1],
                    -signal_cache[r.tag][2],
                    -signal_cache[r.tag][3],
                    -int(r.post_count),
                    r.tag,
                )
            )

            if len(rows) > MAX_ROWS_PER_REGION:
                rows = rows[:MAX_ROWS_PER_REGION]

            by_subgroup: dict[str, list[RegionTag]] = defaultdict(list)
            for r in rows:
                subgroup = self._assigned_group_by_tag.get(r.tag, "other")
                by_subgroup[subgroup].append(r)

            # 서브그룹 통계 + 정렬
            subgroup_stats: dict[str, tuple] = {}
            for sg, items in by_subgroup.items():
                reco_sum = 0.0
                reco_max = 0.0
                pair_conf_max = 0.0
                signal_hits = 0
                pair_conf_sum = 0.0
                pair_hits_sum = 0
                pair_max_count = 0
                post_sum = 0
                for x in items:
                    rs, pc, ph, pcc = signal_cache.get(x.tag, self._tag_signal(x.tag))
                    if rs > 0.0 or pc > 0.0:
                        signal_hits += 1
                    reco_sum += rs
                    reco_max = max(reco_max, rs)
                    pair_conf_max = max(pair_conf_max, pc)
                    pair_conf_sum += pc
                    pair_hits_sum += ph
                    pair_max_count = max(pair_max_count, pcc)
                    post_sum += int(x.post_count)
                subgroup_stats[sg] = (
                    reco_sum, reco_max, pair_conf_max, signal_hits,
                    pair_conf_sum, pair_hits_sum, pair_max_count, post_sum,
                )

            subgroup_order = sorted(
                by_subgroup.keys(),
                key=lambda sg: (
                    -subgroup_stats[sg][0],
                    -subgroup_stats[sg][1],
                    -subgroup_stats[sg][2],
                    -subgroup_stats[sg][3],
                    -subgroup_stats[sg][4],
                    -subgroup_stats[sg][5],
                    -subgroup_stats[sg][6],
                    -subgroup_stats[sg][7],
                    sg,
                ),
            )

            tree.setUpdatesEnabled(False)
            tree.clear()
            sg_brush = QBrush(QColor("#2B2B2B"))
            item_brush = QBrush(QColor("#212121"))
            parents_batch: list[QTreeWidgetItem] = []
            for sg in subgroup_order:
                items = by_subgroup[sg]
                parent = QTreeWidgetItem([f"{sg} ({len(items)})"])
                parent.setData(0, Qt.ItemDataRole.UserRole, "")
                parent.setData(0, Qt.ItemDataRole.UserRole + 1, sg)
                sg_total = sum(int(x.post_count) for x in items)
                parent.setToolTip(0, f"Posts: {fmt_k_count(sg_total)}")
                parent.setBackground(0, sg_brush)
                children: list[QTreeWidgetItem] = []
                for x in items:
                    count_str = fmt_k_count(int(x.post_count))
                    child = QTreeWidgetItem([f"{x.tag}  ({count_str})"])
                    child.setData(0, Qt.ItemDataRole.UserRole, x.tag)
                    child.setBackground(0, item_brush)
                    tip = self._make_tag_tooltip(x.tag)
                    if tip:
                        child.setToolTip(0, tip)
                    children.append(child)
                parent.addChildren(children)
                parents_batch.append(parent)
            tree.addTopLevelItems(parents_batch)

            for p in parents_batch:
                sg_key = p.data(0, Qt.ItemDataRole.UserRole + 1)
                p.setExpanded(isinstance(sg_key, str) and sg_key in expanded_subgroups)

            tree.setUpdatesEnabled(True)
            total = len(all_rows)
            self._region_count_labels[slot].setText(
                f"{len(rows):,} / {int(total):,}"
            )
            if tree.topLevelItemCount() > 0 and not tree.selectedItems():
                tree.setCurrentItem(tree.topLevelItem(0))

    # ------------------------------------------------------------------
    # 표현 테이블
    # ------------------------------------------------------------------

    def _current_selected_combo(self) -> str:
        row = self._combo_table.currentIndex().row()
        if row < 0 or row >= len(self._filtered_combo_summaries):
            return ""
        return self._filtered_combo_summaries[row].clothing_combo

    def _refresh_expected_expressions(self) -> None:
        grouped = build_expression_group_tree(self._expr_global)
        total = sum(len(v) for v in grouped.values())

        self._expr_tree.setUpdatesEnabled(False)
        self._expr_tree.clear()

        # EXPRESSION_GROUPS 순서대로, 이후 base/other
        group_order = [key for key, _label, _anchors in EXPRESSION_GROUPS]
        for extra in ("base", "other"):
            if extra not in group_order:
                group_order.append(extra)

        label_map = {key: label for key, label, _a in EXPRESSION_GROUPS}
        label_map["base"] = "base (수식어만)"
        label_map["other"] = "other (미분류)"

        for gkey in group_order:
            rows = grouped.get(gkey)
            if not rows:
                continue
            label = label_map.get(gkey, gkey)
            parent = QTreeWidgetItem([f"{label} ({len(rows)})"])
            parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for r in rows:
                combo = str(r["expression_combo"])
                count = int(r.get("count", 0))
                count_str = f"{count:,}" if count >= 1000 else str(count)
                child = QTreeWidgetItem([f"{combo}  ({count_str})"])
                child.setData(0, Qt.ItemDataRole.UserRole, combo)
                parent.addChild(child)
            self._expr_tree.addTopLevelItem(parent)

        self._expr_tree.setUpdatesEnabled(True)
        self._expr_count_label.setText(f"{total:,} expression sets")

    def _on_expr_tree_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        if item.parent() is None:
            return
        combo = item.data(0, Qt.ItemDataRole.UserRole)
        if not combo:
            return
        # 같은 항목 재클릭 → 해제
        if item is self._pinned_expr_item:
            self._staged_expressions = []
            self._update_expr_item_style(item, False)
            self._pinned_expr_item = None
        else:
            # 이전 고정 해제
            if self._pinned_expr_item is not None:
                self._update_expr_item_style(self._pinned_expr_item, False)
            # 새 고정
            self._staged_expressions = [t.strip() for t in combo.split(",") if t.strip()]
            self._update_expr_item_style(item, True)
            self._pinned_expr_item = item
        self._rebuild_prompt_preview()

    def _update_expr_item_style(self, item: QTreeWidgetItem, pinned: bool) -> None:
        item.setData(0, PINNED_ROLE, pinned)

    # ------------------------------------------------------------------
    # 번역 패널
    # ------------------------------------------------------------------

    def _refresh_translation_panel(self) -> None:
        """현재 표시 중인 번역 정보 유지 (자동 갱신하지 않음)."""
        pass

    def _hide_info_labels(self) -> None:
        """번역 패널 플레이스홀더로 초기화."""
        fs = get_scaled_font_size
        self._info_label.setText(
            f'<span style="color:#555555; font-size:{fs(18)}px; font-weight:bold;">Translated Tags</span><br>'
            f'<span style="color:#888888; font-size:{fs(15)}px;">아이템을 선택하거나, 마우스를 올려두면 번역이 나타납니다.</span>'
        )

    def _lookup_tag_translation(self, tag_name: str) -> tuple[str, str]:
        """KR_tags에서 태그 번역 조회. (category, desc) 반환. O(1) 캐시 사용."""
        if not tag_name:
            return "", ""
        result = self._kr_tag_cache.get(tag_name)
        if result is not None:
            return result
        tag_norm = tag_name.replace("_", " ")
        result = self._kr_tag_cache.get(tag_norm)
        if result is not None:
            return result
        return "", ""

    def _make_tag_tooltip(self, tag_name: str) -> str:
        """태그 번역 툴팁 문자열 생성."""
        cat, desc = self._lookup_tag_translation(tag_name)
        parts: list[str] = [tag_name]
        if cat:
            parts[0] += f"  ({cat})"
        if desc:
            parts.append(desc)
        return "\n".join(parts) if desc or cat else ""

    def _update_tag_info(self, tag_name: str) -> None:
        """단일 태그의 KR_tags 정보를 단일 RichText 라벨에 표시.

        1줄: 태그명 (어두운 파란색 볼드) + 카테고리 (회색)
        2줄: 설명 (검은색, +2px)
        """
        if not tag_name:
            self._hide_info_labels()
            return

        fs = get_scaled_font_size
        cat, desc_text = self._lookup_tag_translation(tag_name)

        tag_html = f'<span style="color:#1A5276; font-size:{fs(18)}px; font-weight:bold;">{tag_name}</span>'
        if cat:
            tag_html += f'  <span style="color:#555555; font-size:{fs(16)}px;">{cat}</span>'

        desc_html = ""
        if desc_text:
            desc_html = f'<br><span style="color:#1A1A1A; font-size:{fs(18)}px;">{desc_text}</span>'

        self._info_label.setText(f"{tag_html}{desc_html}")

    # ------------------------------------------------------------------
    # 프롬프트
    # ------------------------------------------------------------------

    def _get_selected_rating_tags(self) -> list[str]:
        """체크된 rating 체크박스에 대응하는 태그 리스트 반환."""
        _RATING_TAG_MAP = {
            "general": ["general", "safe"],
            "sensitive": ["sensitive"],
            "questionable": ["questionable", "nsfw"],
            "explicit": ["explicit", "nsfw"],
        }
        tags: list[str] = []
        for name, cb in self._rating_checkboxes.items():
            if cb.isChecked():
                tags.extend(_RATING_TAG_MAP[name])
        # 중복 제거 (순서 보존)
        seen: set[str] = set()
        unique: list[str] = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique

    def _on_rating_toggled(self, name: str, checked: bool) -> None:
        """rating 체크박스 토글 → 프롬프트 갱신."""
        self._rebuild_prompt_preview()

    def _rebuild_prompt_preview(self) -> None:
        # Global Stage (promoted) + Local Stage (region) 합집합
        seen: set[str] = set()
        clothing_tags: list[str] = []
        for slot in DISPLAY_SLOTS:
            for tag in self._region_staged.get(slot, []):
                if tag and tag not in seen:
                    seen.add(tag)
                    clothing_tags.append(tag)
        # Expression 태그 (비의상)
        expr_tags: list[str] = []
        for tag in self._staged_expressions:
            if tag and tag not in seen:
                seen.add(tag)
                expr_tags.append(tag)
        rating_tags = self._get_selected_rating_tags()

        # 프롬프트 텍스트 빌드 (plain text — 복사/생성용)
        all_tags = clothing_tags + expr_tags
        text = PromptBuilder.build(all_tags, self._current_combo, rating_tags=rating_tags)

        # HTML 빌드 — 비의상 태그 회색, 의상 태그 흰색
        _GRAY_TAGS = {"1girl", "general", "sensitive", "questionable", "explicit", "safe", "nsfw"}
        clothing_set = set(clothing_tags)
        parts = [t.strip() for t in text.split(",") if t.strip()]
        html_parts: list[str] = []
        for p in parts:
            if p in _GRAY_TAGS or p not in clothing_set:
                html_parts.append(f'<span style="color:#777777;">{p}</span>')
            else:
                html_parts.append(f'<span style="color:#EEEEEE;">{p}</span>')
        html = ", ".join(html_parts)

        self._prompt_edit.setHtml(
            f'<div style="font-size:{get_scaled_font_size(17)}px;">{html}</div>'
        )
        # plain text 보관
        self._prompt_plain_text = text
        # 의상 태그만 (Copy to Clipboard 용)
        self._clothing_only_text = ", ".join(clothing_tags) if clothing_tags else ""

    def _on_copy_to_clipboard(self) -> None:
        text = getattr(self, '_clothing_only_text', '') or ''
        if not text:
            return
        QApplication.clipboard().setText(text)

    # ------------------------------------------------------------------
    # 생성 (event_preset 패턴)
    # ------------------------------------------------------------------

    def _set_generating_state(self, generating: bool) -> None:
        self._generating = generating
        self._generate_btn.setEnabled(not generating)
        self._generate_btn.setText("Generating..." if generating else "Generate")
        self._lucky_btn.setEnabled(not generating)

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
            'auto_generate': False,
            'turbo_mode': cb["터보 옵션"].isChecked(),
            'wildcard_standalone': cb["와일드카드 단독 모드"].isChecked(),
            'api_mode': main_window.app_context.get_api_mode(),
            'comfyui_sampling_mode': comfyui_sampling_mode,
        }

    def _on_generate_clicked(self) -> None:
        """Generate 클릭 → 프롬프트 파이프라인 경유 → 이미지 생성 (메인 프롬프트 변경 없음)."""
        if not self.app_context or self._generating:
            return

        main_window = getattr(self.app_context, "main_window", None)
        if not main_window:
            return

        prompt = getattr(self, '_prompt_plain_text', '') or self._prompt_edit.toPlainText().strip()
        if not prompt:
            return

        try:
            self._set_generating_state(True)

            # 메인 윈도우 settings 수집
            settings = self._collect_main_settings(main_window)

            # 프롬프트를 파이프라인에 통과 (silent — 메인 창 무변경)
            self.app_context.skip_prompt_engineering_auto_hide = True
            tags_dict = {"general": prompt}
            processed = main_window.prompt_gen_controller.generate_instant_source_silent(
                tags_dict, settings,
            )
            final_prompt = processed or prompt

            # 처리된 프롬프트로 이미지 생성 요청 (832×1216 고정)
            override_params = {
                "input": final_prompt,
                "clothes_preset_request": True,
                "width": 832,
                "height": 1216,
            }

            self.app_context.subscribe(
                "generation_completed_for_clothes_preset",
                self._on_generate_completed,
            )
            self.app_context.subscribe("generation_error", self._on_generate_error)

            print(f"[ClothesPreset] 생성 시작: overrides={list(override_params.keys())}, prompt={final_prompt[:60]}...")
            main_window.generation_controller.execute_generation_pipeline(
                overrides=override_params,
            )

        except Exception as e:
            print(f"[ClothesPreset] 생성 오류: {e}")
            self._set_generating_state(False)

    def _on_lucky_clicked(self) -> None:
        """I Feel Lucky: 스테이징 초기화 → tag>=4 콤보 중 랜덤 1개 스테이징 → Generate."""
        if not self._data_loaded or self._generating:
            return
        self._run_lucky_round()
        # 자동 랜덤 체크박스 노출
        self._show_auto_random_cb()

    def _run_lucky_round(self) -> None:
        """Lucky 1회 실행: 랜덤 콤보 선택 → 스테이징 → Generate."""
        import random
        candidates = [
            c for c in self._combo_summaries
            if c.tag_count >= 4
            and "cosplay" not in c.clothing_combo
            and "alternate" not in c.clothing_combo
        ]
        if not candidates:
            return
        chosen = random.choice(candidates)
        # 1. 스테이징 초기화
        self._staged_tags = []
        self._region_staged = {s: [] for s in DISPLAY_SLOTS}
        self._promoted_set = set()
        self._promoted_set_balanced = set()
        self._staged_expressions = []
        self._pinned_expr_item = None
        self._reset_expr_tree_styles()
        # 2. 선택된 콤보 태그를 스테이징
        self._stage_combo_tags(chosen.tags)
        # 3. Generate
        self._lucky_generating = True
        self._on_generate_clicked()

    def _show_auto_random_cb(self) -> None:
        """자동 랜덤 체크박스를 즉시 보이게 (페이드 중이면 중단)."""
        self._auto_random_fade_timer.stop()
        if self._auto_random_fade_anim is not None:
            self._auto_random_fade_anim.stop()
            self._auto_random_fade_anim = None
        self._auto_random_opacity.setOpacity(1.0)
        self._auto_random_cb.setVisible(True)

    def _on_automation_stopped(self, *args) -> None:
        """자동화 중단/완료 시 자동 랜덤 체크 해제."""
        if self._auto_random_cb.isChecked():
            self._auto_random_cb.setChecked(False)
            print("[ClothesPreset] 자동화 중단으로 자동 랜덤 해제")

    def _get_automation_delay_ms(self) -> int:
        """자동화 모듈의 생성 딜레이를 ms로 반환. 없으면 기본 300ms."""
        try:
            if self.app_context and hasattr(self.app_context, 'main_window'):
                module = getattr(self.app_context.main_window, 'automation_module', None)
                if module:
                    delay = module.get_generation_delay()
                    if delay > 0:
                        return int(delay * 1000)
        except Exception:
            pass
        return 300

    def _on_auto_random_toggled(self, checked: bool) -> None:
        """체크 시 페이드 타이머 취소, 항상 보이도록."""
        if checked:
            self._auto_random_fade_timer.stop()
            if self._auto_random_fade_anim is not None:
                self._auto_random_fade_anim.stop()
                self._auto_random_fade_anim = None
            self._auto_random_opacity.setOpacity(1.0)

    def _start_auto_random_fade(self) -> None:
        """5초 경과 후 체크 안 됐으면 페이드아웃."""
        if self._auto_random_cb.isChecked():
            return
        anim = QPropertyAnimation(self._auto_random_opacity, b"opacity", self)
        anim.setDuration(800)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InQuad)
        anim.finished.connect(self._on_auto_random_fade_done)
        self._auto_random_fade_anim = anim
        anim.start()

    def _on_auto_random_fade_done(self) -> None:
        """페이드 완료 후 숨김."""
        self._auto_random_cb.setVisible(False)
        self._auto_random_opacity.setOpacity(1.0)
        self._auto_random_fade_anim = None

    def _on_generate_completed(self, image_obj) -> None:
        print(f"[ClothesPreset] _on_generate_completed 호출됨, image_obj type={type(image_obj)}")
        self._unsubscribe_generation()
        self._set_generating_state(False)
        was_lucky = self._lucky_generating
        self._lucky_generating = False
        if image_obj is None:
            return
        try:
            from io import BytesIO
            buf = BytesIO()
            image_obj.save(buf, format="PNG")
            buf.seek(0)
            qimg = QImage()
            qimg.loadFromData(buf.read())
            if qimg.isNull():
                return
            self._qimage_ref = qimg  # prevent GC
            pix = QPixmap.fromImage(qimg)
            scaled = pix.scaled(
                self._image_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._image_preview.setPixmap(scaled)
        except Exception as e:
            print(f"[ClothesPreset] 이미지 표시 실패: {e}")

        # 자동 랜덤: 체크 상태면 다음 라운드 (자동화 딜레이 반영), 아니면 5초 후 페이드아웃
        if was_lucky:
            if self._auto_random_cb.isChecked():
                delay_ms = self._get_automation_delay_ms()
                QTimer.singleShot(delay_ms, self._run_lucky_round)
            else:
                self._auto_random_fade_timer.start(5000)

    def _on_generate_error(self, error_data) -> None:
        is_ours = (
            isinstance(error_data, dict)
            and error_data.get("clothes_preset_request")
        )
        if not is_ours:
            return
        self._unsubscribe_generation()
        self._set_generating_state(False)
        self._lucky_generating = False
        print(f"[ClothesPreset] 생성 에러: {error_data.get('message', '')}")

    def _unsubscribe_generation(self) -> None:
        if not self.app_context:
            return
        for event_name, callback in [
            ("generation_completed_for_clothes_preset", self._on_generate_completed),
            ("generation_error", self._on_generate_error),
        ]:
            subs = self.app_context.subscribers.get(event_name)
            if subs and callback in subs:
                subs.remove(callback)

    # ------------------------------------------------------------------
    # 윈도우 이벤트
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self._unsubscribe_generation()
        # 자동화 중단 이벤트 구독 해제
        if self.app_context:
            subs = self.app_context.subscribers.get("automation_stopped")
            if subs and self._on_automation_stopped in subs:
                subs.remove(self._on_automation_stopped)
        self._dm.close()
        self.window_closed.emit()
        super().closeEvent(event)
