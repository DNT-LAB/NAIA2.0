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
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
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
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui.theme import DARK_COLORS
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

from .data_manager import (
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
from .engines import (
    DISPLAY_SLOTS,
    MAX_COMBO_ROWS_DISPLAY,
    MAX_ROWS_PER_REGION,
    PAIR_MODE_PROFILES,
    REGIONS,
    SEARCH_DEBOUNCE_MS,
    SLOT_LABELS,
    ClothingTaxonomyEngine,
    ExpressionEngine,
    PromptBuilder,
    RulesEngine,
)
from .widgets import ComboTableModel, FlowLayout, StagedTagChip


# ---------------------------------------------------------------------------
# 데이터 경로
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent
DATA_ZIP_PATH = DATA_DIR / PACKAGE_FILE_NAME


# ---------------------------------------------------------------------------
# 메인 윈도우
# ---------------------------------------------------------------------------

class ClothesPresetWindow(QMainWindow):
    """Clothes Preset 메인 윈도우 — 의류 택소노미 브라우저."""

    window_closed = pyqtSignal()
    apply_to_main_prompt = pyqtSignal(dict)

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

        msg = QMessageBox(parent)
        msg.setWindowTitle("Clothes Preset 데이터")
        msg.setText(
            "Clothes Preset 데이터가 없습니다.\n"
            "다운로드하시겠습니까?"
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.Yes)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return False

        success_flag = [False]

        def on_finished(success: bool, message: str):
            success_flag[0] = success
            if not success:
                QMessageBox.warning(parent, "다운로드 실패", message)
            dialog.mark_finished()

        dialog = ClothesPresetDownloadDialog(parent)
        worker = ClothesPresetDownloadWorker(DATA_ZIP_PATH)
        worker.progress_updated.connect(dialog.update_progress)
        worker.download_finished.connect(on_finished)
        dialog.canceled.connect(worker.cancel)

        worker.start()
        dialog.exec()
        worker.wait()

        return success_flag[0]

    # ------------------------------------------------------------------
    # 생성자
    # ------------------------------------------------------------------

    def __init__(self, app_context=None, kr_tags_df=None, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._kr_tags_df = kr_tags_df if kr_tags_df is not None else pd.DataFrame()

        self.setWindowTitle("Clothes Preset")
        self.setMinimumSize(get_scaled_size(1680), get_scaled_size(980))
        self.resize(get_scaled_size(1960), get_scaled_size(1190))

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
        self._active_slot: str = DISPLAY_SLOTS[0]
        self._pair_mode = "Balanced"
        self._generating = False
        self._qimage_ref = None  # GC 방지
        self._seed_region_counts: dict[str, int] = {r: 0 for r in REGIONS}

        # 한글→영어 검색 인덱스 (kr_tags_df 기반)
        self._kr_search_index: dict[str, set[str]] = {}
        self._build_kr_search_index()

        # UI 빌드
        self._build_ui()
        self._init_debounce_timers()
        self._apply_theme()

        # 데이터 로드
        self._dm = ClothesPresetDataManager()
        self._load_all()
        self._refresh_combo_candidates_from_stage()

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
        self._panel_ratio = (1.0, 2.4, 1.0)

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

        self._combo_count_label = QLabel("0 combos")
        left_l.addWidget(self._combo_count_label)

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
        self._combo_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        combo_header = self._combo_table.horizontalHeader()
        combo_header.setStretchLastSection(False)
        combo_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        combo_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._combo_table.setColumnWidth(1, get_scaled_size(55))
        self._combo_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._combo_table.customContextMenuRequested.connect(self._on_combo_context_menu)
        self._combo_table.selectionModel().currentRowChanged.connect(
            lambda _cur, _prev: self._on_combo_selected()
        )
        left_splitter.addWidget(self._combo_table)

        # Expression 테이블
        expr_widget = QWidget()
        expr_l = QVBoxLayout(expr_widget)
        expr_l.setContentsMargins(0, 0, 0, 0)
        expr_l.setSpacing(get_scaled_size(2))
        self._expr_count_label = QLabel("0 expression sets")
        expr_l.addWidget(self._expr_count_label)
        self._expr_table = QTableWidget()
        self._expr_table.setColumnCount(3)
        self._expr_table.setHorizontalHeaderLabels(["Expression Set", "Count", "Conf"])
        self._expr_table.horizontalHeader().setStretchLastSection(True)
        self._expr_table.setColumnWidth(1, get_scaled_size(55))
        self._expr_table.setColumnWidth(2, get_scaled_size(75))
        self._expr_table.verticalHeader().setVisible(False)
        self._expr_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._expr_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._expr_table.setSortingEnabled(True)
        expr_l.addWidget(self._expr_table)
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

        # 우측: 번역 2줄 (태그+카테고리 / 설명)
        info_box = QVBoxLayout()
        info_box.setSpacing(get_scaled_size(1))
        self._info_line1 = QLabel("")
        self._info_line1.setObjectName("infoLine1")
        self._info_line1.setTextFormat(Qt.TextFormat.RichText)
        self._info_line1.setWordWrap(True)
        info_box.addWidget(self._info_line1)
        self._info_line2 = QLabel("")
        self._info_line2.setObjectName("infoLine2")
        self._info_line2.setWordWrap(True)
        info_box.addWidget(self._info_line2)
        top_bar.addLayout(info_box, 4)

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
            stage_panel.setMaximumHeight(get_scaled_size(80))
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
        self._image_preview.setMinimumSize(get_scaled_size(208), get_scaled_size(304))
        self._image_preview.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )
        self._image_preview.setText("832 × 1216")
        right_l.addWidget(self._image_preview, stretch=1)

        # Generate 버튼
        self._generate_btn = QPushButton("Generate")
        self._generate_btn.setFixedWidth(get_scaled_size(130))
        self._generate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._generate_btn.clicked.connect(self._on_generate_clicked)
        gen_row = QHBoxLayout()
        gen_row.addStretch(1)
        gen_row.addWidget(self._generate_btn)
        gen_row.addStretch(1)
        right_l.addLayout(gen_row)

        # 프롬프트
        prompt_label = QLabel("Prompt")
        right_l.addWidget(prompt_label)
        self._prompt_edit = QTextEdit()
        self._prompt_edit.setAcceptRichText(False)
        self._prompt_edit.setPlaceholderText("Prompt preview based on current staged tags")
        self._prompt_edit.setMaximumHeight(get_scaled_size(120))
        right_l.addWidget(self._prompt_edit)

        # 버튼 행: [메인 프롬프트에 전송] [전송 + 즉시 생성]
        btn_row = QHBoxLayout()
        btn_row.setSpacing(get_scaled_size(4))

        self._send_to_main_btn = QPushButton("메인 프롬프트에 전송")
        self._send_to_main_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_to_main_btn.clicked.connect(self._on_send_to_main)
        btn_row.addWidget(self._send_to_main_btn)

        self._send_and_gen_btn = QPushButton("전송 + 즉시 생성")
        self._send_and_gen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_and_gen_btn.clicked.connect(self._on_send_and_generate)
        btn_row.addWidget(self._send_and_gen_btn)
        right_l.addLayout(btn_row)

        # 유틸 행: [Copy to Clipboard] [Clear All Staged]
        util_row = QHBoxLayout()
        util_row.setSpacing(get_scaled_size(4))
        self._copy_btn = QPushButton("Copy to Clipboard")
        self._copy_btn.clicked.connect(self._on_copy_to_clipboard)
        util_row.addWidget(self._copy_btn)
        self._clear_all_btn = QPushButton("Clear All Staged")
        self._clear_all_btn.clicked.connect(self._clear_staging)
        util_row.addWidget(self._clear_all_btn)
        right_l.addLayout(util_row)

        # 스플리터에 패널 추가 + 핸들 드래그 비활성
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
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                gridline-color: {DARK_COLORS['border']};
                font-size: {fs(19)}px;
                alternate-background-color: {DARK_COLORS['bg_primary']};
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

        # 번역 바 스타일 (2줄 컴팩트)
        self._info_line1.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']}; font-size: {fs(15)}px; border: none; padding: 0px;"
        )
        self._info_line2.setStyleSheet(
            f"color: {DARK_COLORS['text_primary']}; font-size: {fs(14)}px; border: none; padding: 0px;"
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

        # Generate 버튼 (event_preset 패턴)
        self._generate_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                color: white;
                font-weight: 600;
                padding: {ss(6)}px {ss(16)}px;
                border-radius: {ss(4)}px;
                font-size: {fs(19)}px;
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

        # 전송 버튼 스타일
        send_btn_style = f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
                padding: {ss(6)}px {ss(12)}px;
                border-radius: {ss(4)}px;
                font-size: {fs(14)}px;
                border: 1px solid {DARK_COLORS['border']};
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['border']};
            }}
        """
        self._send_to_main_btn.setStyleSheet(send_btn_style)
        self._send_and_gen_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
                padding: {ss(6)}px {ss(12)}px;
                border-radius: {ss(4)}px;
                font-size: {fs(14)}px;
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['border']};
            }}
        """)

    # ------------------------------------------------------------------
    # 패널 비율 고정
    # ------------------------------------------------------------------

    def _apply_panel_ratio(self) -> None:
        """1:2.4:1 비율로 스플리터 크기 고정."""
        sp = self._main_splitter
        available = sp.width() - sp.handleWidth() * (sp.count() - 1)
        if available <= 0:
            return
        r = self._panel_ratio
        total = sum(r)
        sizes = [int(available * v / total) for v in r]
        sizes[-1] = available - sum(sizes[:-1])  # 나머지 보정
        sp.setSizes(sizes)

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
        self._combo_search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._combo_search_timer.timeout.connect(self._refresh_combo_candidates_from_stage)

        self._region_search_timer = QTimer(self)
        self._region_search_timer.setSingleShot(True)
        self._region_search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._region_search_timer.timeout.connect(self._refresh_region_tables)

    def _on_combo_search_changed(self, _text: str) -> None:
        self._combo_search_timer.start()

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
                    self._refresh_expected_expressions()
                    return
        if not self._combo_initialized_once and self._filtered_combo_summaries:
            self._combo_initialized_once = True
            self._combo_table.selectRow(0)
        self._refresh_expected_expressions()

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
        self._refresh_expected_expressions()
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

    def _stage_combo_tags(self, tags: tuple[str, ...]) -> None:
        if not tags:
            return
        staged_set = set(self._staged_tags)
        added = False
        for t in tags:
            if not t or t in staged_set:
                continue
            self._staged_tags.append(t)
            staged_set.add(t)
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

    def _add_selected_region_tag(self, slot: str | None = None) -> None:
        tag = self._selected_region_tag(slot)
        if not tag or tag in self._staged_tags:
            return
        self._staged_tags.append(tag)
        self._refresh_all_from_staging()

    def _clear_staging(self) -> None:
        self._staged_tags = []
        self._region_staged = {s: [] for s in DISPLAY_SLOTS}
        self._refresh_all_from_staging()

    # ------------------------------------------------------------------
    # Pair 모드
    # ------------------------------------------------------------------

    def _on_pair_mode_changed(self, mode: str) -> None:
        if mode not in PAIR_MODE_PROFILES:
            return
        self._pair_mode = mode
        self._refresh_all_from_staging()

    # ------------------------------------------------------------------
    # 갱신 캐스케이드
    # ------------------------------------------------------------------

    def _refresh_all_from_staging(self) -> None:
        self._combo_search_timer.stop()
        self._region_search_timer.stop()
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
        region_lookup = {r.tag: r for r in self._region_tags}
        by_slot: dict[str, list[str]] = {s: [] for s in DISPLAY_SLOTS}
        for tag in self._staged_tags:
            slot = self._slot_for_tag(tag, region_lookup)
            if slot in by_slot:
                by_slot[slot].append(tag)

        # region_staged 동기화
        self._region_staged = {s: list(tags) for s, tags in by_slot.items()}

        for slot in DISPLAY_SLOTS:
            flow = self._slot_chip_layouts.get(slot)
            if flow is None:
                continue
            flow.clear_widgets()
            tags = by_slot.get(slot, [])
            slot_color = self._slot_accent_colors.get(slot, "")
            for tag in tags:
                chip = StagedTagChip(tag, border_color=slot_color)
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
        """칩 × 클릭 → staged에서 태그 제거."""
        if tag in self._staged_tags:
            self._staged_tags.remove(tag)
            self._refresh_all_from_staging()

    def _on_slot_clear(self, slot: str) -> None:
        """해당 슬롯의 staged 태그 전부 제거."""
        region_lookup = {r.tag: r for r in self._region_tags}
        to_remove = [
            tag for tag in self._staged_tags
            if self._slot_for_tag(tag, region_lookup) == slot
        ]
        if not to_remove:
            return
        for tag in to_remove:
            self._staged_tags.remove(tag)
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
        staged = set(self._staged_tags)
        candidate_set: set[str] = set(staged)

        # 한글 검색 지원
        kr_matched_tags: set[str] = set()
        if keyword:
            kr_matched_tags = self._kr_search(keyword)

        if staged:
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
            if staged:
                rows = [r for r in rows if r.tag in candidate_set]
            rows = [r for r in rows if r.tag not in staged]

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
                    0 if r.tag in staged else 1,
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
                    children.append(child)
                parent.addChildren(children)
                parents_batch.append(parent)
            tree.addTopLevelItems(parents_batch)

            for p in parents_batch:
                sg_key = p.data(0, Qt.ItemDataRole.UserRole + 1)
                p.setExpanded(isinstance(sg_key, str) and sg_key in expanded_subgroups)

            tree.setUpdatesEnabled(True)
            total = len(all_rows)
            subgroup_count = len(subgroup_order)
            self._region_count_labels[slot].setText(
                f"showing {len(rows):,} / {int(total):,} | subgroup {subgroup_count}"
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
        selected_combo = self._current_selected_combo()
        staged = [t for t in self._staged_tags if t]
        source = "global"

        if selected_combo and selected_combo in self._expr_by_combo:
            rows = list(self._expr_by_combo.get(selected_combo, []))
            source = "selected combo"
        elif staged:
            rows = ExpressionEngine.aggregate_for_staged(staged, self._expr_by_combo)
            source = "staged-match"
        else:
            rows = list(self._expr_global)

        max_rows = 300
        shown = rows[:max_rows]
        prev_sort = self._expr_table.isSortingEnabled()
        self._expr_table.setUpdatesEnabled(False)
        self._expr_table.setSortingEnabled(False)
        self._expr_table.setRowCount(len(shown))
        for i, r in enumerate(shown):
            self._expr_table.setItem(i, 0, QTableWidgetItem(str(r["expression_combo"])))
            it1 = QTableWidgetItem(f"{int(r['count']):,}")
            it2 = QTableWidgetItem(f"{float(r['confidence']):.4f}")
            it1.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            it2.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._expr_table.setItem(i, 1, it1)
            self._expr_table.setItem(i, 2, it2)
        self._expr_table.setSortingEnabled(prev_sort)
        self._expr_table.setUpdatesEnabled(True)
        self._expr_count_label.setText(f"{len(shown):,} / {len(rows):,} expression sets ({source})")

    # ------------------------------------------------------------------
    # 번역 패널
    # ------------------------------------------------------------------

    def _refresh_translation_panel(self) -> None:
        """현재 표시 중인 번역 정보 유지 (자동 갱신하지 않음)."""
        pass

    def _hide_info_labels(self) -> None:
        """번역 바 초기화."""
        self._info_line1.setText("")
        self._info_line2.setText("")

    def _update_tag_info(self, tag_name: str) -> None:
        """단일 태그의 KR_tags 정보를 2줄 번역 바에 표시.

        Line 1: <tag name 연노랑> <category 연회색>
        Line 2: <desc 흰색>
        """
        self._hide_info_labels()
        if not tag_name:
            return

        # 기본값 — DB 매칭 실패 시 태그명만 표시
        tag_html = f'<span style="color:#F5E6A3; font-weight:bold;">{tag_name}</span>'
        category_html = ""
        desc_text = ""

        if self._kr_tags_df is not None and not self._kr_tags_df.empty:
            rows = self._kr_tags_df[self._kr_tags_df["tag"] == tag_name]
            if rows.empty:
                tag_norm = tag_name.replace("_", " ")
                rows = self._kr_tags_df[self._kr_tags_df["tag"] == tag_norm]
            if not rows.empty:
                data = rows.iloc[0]
                # 카테고리
                cat = str(data.get("category", "")) if pd.notna(data.get("category")) else ""
                if cat:
                    category_html = f'  <span style="color:#B0B0B0;">{cat}</span>'
                # 설명
                desc_text = str(data.get("desc", "")) if pd.notna(data.get("desc")) else ""

        # Line 1: 태그명 + 카테고리
        self._info_line1.setText(f"{tag_html}{category_html}")

        # Line 2: 설명
        self._info_line2.setText(desc_text)

    # ------------------------------------------------------------------
    # 프롬프트
    # ------------------------------------------------------------------

    def _rebuild_prompt_preview(self) -> None:
        text = PromptBuilder.build(self._staged_tags, self._current_combo)
        self._prompt_edit.setPlainText(text)

    def _on_copy_to_clipboard(self) -> None:
        text = self._prompt_edit.toPlainText().strip()
        if not text:
            return
        QApplication.clipboard().setText(text)

    # ------------------------------------------------------------------
    # 생성 (event_preset 패턴)
    # ------------------------------------------------------------------

    def _set_generating_state(self, generating: bool) -> None:
        self._generating = generating
        self._generate_btn.setEnabled(not generating)
        self._send_and_gen_btn.setEnabled(not generating)
        self._generate_btn.setText("Generating..." if generating else "Generate")

    def _on_generate_clicked(self) -> None:
        """Generate 클릭 → 프롬프트 파이프라인 경유 → 이미지 생성 (메인 프롬프트 변경 없음)."""
        if not self.app_context or self._generating:
            return
        prompt = self._prompt_edit.toPlainText().strip()
        if not prompt:
            return

        self._set_generating_state(True)

        main_window = getattr(self.app_context, "main_window", None)
        if not main_window:
            self._set_generating_state(False)
            return

        # 프롬프트 파이프라인 없이 직접 생성
        try:
            gen_input = main_window.prompt_generation_controller.generate_instant_source_silent(
                self.app_context, prompt
            )
        except Exception as e:
            print(f"[ClothesPreset] generate_instant_source_silent 실패: {e}")
            self._set_generating_state(False)
            return

        self.app_context.subscribe(
            "generation_completed_for_clothes_preset",
            self._on_generate_completed,
        )
        self.app_context.subscribe("generation_error", self._on_generate_error)

        override = {
            "clothes_preset_request": True,
            "width": 832,
            "height": 1216,
        }
        main_window.generation_controller.execute_generation_pipeline(
            input=gen_input, overrides=override
        )

    def _on_generate_completed(self, image_obj) -> None:
        self._unsubscribe_generation()
        self._set_generating_state(False)
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

    def _on_generate_error(self, error_data) -> None:
        is_ours = (
            isinstance(error_data, dict)
            and error_data.get("clothes_preset_request")
        )
        if not is_ours:
            return
        self._unsubscribe_generation()
        self._set_generating_state(False)
        print(f"[ClothesPreset] 생성 에러: {error_data.get('message', '')}")

    def _unsubscribe_generation(self) -> None:
        if self.app_context:
            self.app_context.unsubscribe(
                "generation_completed_for_clothes_preset",
                self._on_generate_completed,
            )
            self.app_context.unsubscribe(
                "generation_error", self._on_generate_error
            )

    def _on_send_to_main(self) -> None:
        """현재 프롬프트를 파이프라인 경유로 메인 프롬프트에 전송."""
        prompt = self._prompt_edit.toPlainText().strip()
        if not prompt:
            return
        self.apply_to_main_prompt.emit({"general": prompt})

    def _on_send_and_generate(self) -> None:
        """메인 프롬프트에 파이프라인 경유 전송 + Clothes Preset 내 이미지 생성."""
        prompt = self._prompt_edit.toPlainText().strip()
        if not prompt or self._generating:
            return

        self._set_generating_state(True)
        self.apply_to_main_prompt.emit({"general": prompt})
        QTimer.singleShot(100, self._trigger_send_and_generate)

    def _trigger_send_and_generate(self) -> None:
        main_window = getattr(self.app_context, "main_window", None) if self.app_context else None
        if not main_window:
            self._set_generating_state(False)
            return

        self.app_context.subscribe(
            "generation_completed_for_clothes_preset",
            self._on_send_gen_completed,
        )
        self.app_context.subscribe("generation_error", self._on_send_gen_error)

        override = {
            "clothes_preset_request": True,
            "width": 832,
            "height": 1216,
        }
        main_window.generation_controller.execute_generation_pipeline(
            overrides=override,
        )

    def _on_send_gen_completed(self, image_obj) -> None:
        self._unsubscribe_send_gen()
        self._set_generating_state(False)
        self._on_generate_completed(image_obj)

    def _on_send_gen_error(self, error_data) -> None:
        is_ours = (
            isinstance(error_data, dict)
            and error_data.get("clothes_preset_request")
        )
        if not is_ours:
            return
        self._unsubscribe_send_gen()
        self._set_generating_state(False)

    def _unsubscribe_send_gen(self) -> None:
        if self.app_context:
            self.app_context.unsubscribe(
                "generation_completed_for_clothes_preset",
                self._on_send_gen_completed,
            )
            self.app_context.unsubscribe(
                "generation_error", self._on_send_gen_error
            )

    # ------------------------------------------------------------------
    # 윈도우 이벤트
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self._unsubscribe_generation()
        self._unsubscribe_send_gen()
        self._dm.close()
        self.window_closed.emit()
        super().closeEvent(event)
