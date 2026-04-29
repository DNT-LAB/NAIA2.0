from __future__ import annotations

import io
import itertools
import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QTextDocument
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox,
    QFrame, QHBoxLayout, QHeaderView, QLabel, QLayout,
    QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QPushButton,
    QSizePolicy, QSplitter,
    QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QTableWidget, QTableWidgetItem, QTabWidget,
    QTextEdit, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)


class _FlowLayout(QLayout):
    """Horizontal layout that wraps items to the next line when width is exceeded."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 3) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        w = h = 0
        for item in self._items:
            s = item.minimumSize()
            w = max(w, s.width())
            h = max(h, s.height())
        return QSize(w, h)

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        x = rect.x()
        y = rect.y()
        row_h = 0
        for item in self._items:
            sz = item.sizeHint()
            if x + sz.width() > rect.right() + 1 and x > rect.x():
                x = rect.x()
                y += row_h + self._spacing
                row_h = 0
            if apply:
                item.setGeometry(QRect(x, y, sz.width(), sz.height()))
            x += sz.width() + self._spacing
            row_h = max(row_h, sz.height())
        return y + row_h - rect.y()


DIST_DIR = Path(__file__).resolve().parent
DATA_ZIP_PATH = DIST_DIR / "naia_prompt_preset"


# ---------------------------------------------------------------------------
# ZIP I/O helpers
# ---------------------------------------------------------------------------
_zip_ref: zipfile.ZipFile | None = None


def open_data_zip() -> zipfile.ZipFile:
    """Open (or return cached) data.zip for reading."""
    global _zip_ref
    if _zip_ref is None:
        _zip_ref = zipfile.ZipFile(DATA_ZIP_PATH, "r")
    return _zip_ref


def _zread_parquet(zf: zipfile.ZipFile, name: str) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(zf.read(name)))


def _zread_json(zf: zipfile.ZipFile, name: str) -> Any:
    return json.loads(zf.read(name).decode("utf-8"))


def _zread_text(zf: zipfile.ZipFile, name: str) -> str:
    return zf.read(name).decode("utf-8")


def _zexists(zf: zipfile.ZipFile, name: str) -> bool:
    return name in zf.NameToInfo


TOP_N = 30
STAGED_COMBO_TOP_N = 5
MAX_STAGED = 3
OBSERVED_RETAIN_CONFIDENCE_GT = 0.9
OBSERVED_RETAIN_TOP_N = 12
COOC_EXPR_CONFIDENCE_MIN = 0.10
COOC_CLOTH_CONFIDENCE_MIN = 0.05
COOC_CHAR_CONFIDENCE_MIN = 0.05
COOC_TOP_N_PER_EVENT = 8
COOC_TOP_N_MERGED = 12
COOC_AFFINITY_THRESHOLD = 0.05
ROLE_LEVEL = int(Qt.ItemDataRole.UserRole)
ROLE_EVENT = int(Qt.ItemDataRole.UserRole) + 1

STEP1_REQUIRED = [
    "tag_catalog.parquet",
    "tag_category.parquet",
    "cooccurrence_event_expression.parquet",
    "cooccurrence_event_clothing.parquet",
    "cooccurrence_event_color.parquet",
    "dependency_rules.parquet",
    "quality_metrics.json",
]

STEP3_OPTIONAL = [
    "event_min_ancestor_set.parquet",
    "event_navigation_edges.parquet",
    "event_prompt_only.parquet",
    "step3_metrics.json",
]

STEP7_OPTIONAL = [
    "event_group_mapping.json",
    "event_taxonomy.parquet",
]

STEP9_OPTIONAL = [
    "activity_subcategory_summary.json",
    "event_taxonomy_enriched.parquet",
]

STEP10_OPTIONAL = [
    "subcategory_display_ko.json",
    "event_taxonomy_v2_1.parquet",
    "event_taxonomy_v2.parquet",
    "activity_subcategory_v2_1_summary.json",
    "activity_subcategory_v2_summary.json",
]

RATING_TOGGLES = ["General", "Sensitive", "Question", "Explicit"]
RATING_PREFIX_MAP = {
    "General": "g",
    "Sensitive": "s",
    "Question": "q",
    "Explicit": "e",
}
PERSON_PARTITION_ORDER = [
    "1girl_solo",
    "1girl",
    "1girl_1boy",
    "1girl_multiple_boys",
    "2girls",
    "multiple_girls",
    "1boy_solo",
    "1boy",
    "1boy_multiple_girls",
    "2boys",
    "multiple_boys",
    "multiple_girls_multiple_boys",
    "other",
]
PERSON_PARTITION_LABELS = {
    "1girl_solo": "1girl solo",
    "1girl": "1girl",
    "1girl_1boy": "1girl + 1boy",
    "1girl_multiple_boys": "1girl + multiple boys",
    "2girls": "2girls",
    "multiple_girls": "multiple girls",
    "1boy_solo": "1boy solo",
    "1boy": "1boy",
    "1boy_multiple_girls": "1boy + multiple girls",
    "2boys": "2boys",
    "multiple_boys": "multiple boys",
    "multiple_girls_multiple_boys": "multiple girls + multiple boys",
    "other": "other",
}


def split_csv(text: Any) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        return []
    return [x.strip() for x in text.split(",") if x.strip()]


def join_csv(values: set[str] | list[str]) -> str:
    if not values:
        return ""
    return ", ".join(sorted(values))


def pretty_subcategory_name(key: str) -> str:
    if not key:
        return "Unspecified"
    if key.startswith("holding_"):
        suffix = key[len("holding_") :]
        return f"Holding / {suffix.replace('_', ' ').title()}"
    if key.startswith("activity_"):
        suffix = key[len("activity_") :]
        return suffix.replace("_", " ").title()
    if key.startswith("posture_"):
        suffix = key[len("posture_") :]
        return suffix.replace("_", " ").title()
    if key.startswith("clothing_"):
        suffix = key[len("clothing_") :]
        return suffix.replace("_", " ").title()
    if key.startswith("verb_"):
        suffix = key[len("verb_") :]
        return suffix.replace("_", " ").title()
    if key.startswith("gesture_"):
        suffix = key[len("gesture_") :]
        return suffix.replace("_", " ").title()
    if key.startswith("pose_"):
        suffix = key[len("pose_") :]
        return suffix.replace("_", " ").title()
    return key.replace("_", " ").title()


def default_subcategory_ko_map() -> dict[str, str]:
    return {
        "activity_adjustment": "조정",
        "activity_apparel_adjustment": "의상 조정",
        "activity_oral_action": "구강 동작",
        "activity_performance": "퍼포먼스",
        "activity_locomotion": "이동",
        "activity_other": "기타",
        "holding_weapon": "들기 / 무기",
        "holding_food_drink": "들기 / 음식·음료",
        "holding_clothing": "들기 / 의상",
        "holding_body_self": "들기 / 신체",
        "holding_creature": "들기 / 생물",
        "holding_device_media": "들기 / 디바이스",
        "holding_document_sign": "들기 / 문서·표식",
        "holding_instrument": "들기 / 악기",
        "holding_tool_prop": "들기 / 소도구",
        "holding_misc": "들기 / 기타",
        "sitting": "앉기",
        "standing": "서기",
        "lying": "눕기",
        "kneeling": "무릎 꿇기",
        "crouching": "웅크리기",
        "leaning": "기대기",
        "location": "장소·위치",
        "posture_other": "기타 자세",
        "clothing_adjust": "정돈",
        "clothing_put_on": "입기",
        "clothing_lift": "올리기",
        "clothing_pull": "당기기",
        "clothing_aside": "젖히기",
        "clothing_open": "열기",
        "clothing_displaced": "흐트러짐",
        "clothing_remove": "벗기",
        "clothing_other": "기타 의류",
        "verb_locomotion": "이동",
        "verb_contact": "접촉·교류",
        "verb_eating_drinking": "먹기·마시기",
        "verb_sports": "운동·스포츠",
        "verb_creative": "창작·촬영",
        "verb_grooming": "치장·케어",
        "verb_work": "작업·가사",
        "verb_sound": "소리·발성",
        "verb_sleep": "수면",
        "verb_other": "기타 동사",
        "gesture_hand_sign": "손 기호",
        "gesture_arm_raise": "팔 올리기",
        "gesture_self_face": "얼굴 터치",
        "gesture_self_body": "몸 터치",
        "gesture_covering": "가리기",
        "gesture_pointing": "가리키기",
        "gesture_mouth": "입 접촉",
        "gesture_touch_other": "타인 접촉",
        "gesture_hair": "머리카락",
        "gesture_weapon": "무기·전투",
        "gesture_clothing": "의류 조정",
        "gesture_expressive": "표현·인사",
        "gesture_other": "기타 제스처",
        "pose_between": "사이 배치",
        "pose_on_body": "신체 위",
        "pose_body_display": "신체 강조",
        "pose_arm_rest": "팔 받침",
        "pose_feet_legs": "발·다리",
        "pose_surface": "표면 접촉",
        "pose_acrobatic": "아크로바틱",
        "pose_in_container": "용기 안",
        "pose_carrying": "운반·밀착",
        "pose_restraint": "구속·제압",
        "pose_resting": "안정·휴식",
        "pose_other": "기타 포즈",
    }


def load_assets() -> tuple[dict[str, Any] | None, list[str]]:
    if not DATA_ZIP_PATH.exists():
        return None, [f"data.zip not found: {DATA_ZIP_PATH}"]

    zf = open_data_zip()
    missing = [name for name in STEP1_REQUIRED if not _zexists(zf, f"base/{name}")]
    if missing:
        return None, missing

    assets: dict[str, Any] = {}
    for name in STEP1_REQUIRED:
        arc = f"base/{name}"
        if name.endswith(".parquet"):
            assets[name] = _zread_parquet(zf, arc)
        else:
            assets[name] = _zread_json(zf, arc)

    _OPTIONAL_GROUPS: list[tuple[str, list[str]]] = [
        ("step3", STEP3_OPTIONAL),
        ("step7", STEP7_OPTIONAL),
        ("step9", STEP9_OPTIONAL),
        ("step10", STEP10_OPTIONAL),
    ]
    for prefix, file_list in _OPTIONAL_GROUPS:
        step_missing: list[str] = []
        for name in file_list:
            arc = f"base/{name}"
            if not _zexists(zf, arc):
                step_missing.append(name)
                continue
            if name.endswith(".parquet"):
                assets[f"{prefix}::{name}"] = _zread_parquet(zf, arc)
            else:
                assets[f"{prefix}::{name}"] = _zread_json(zf, arc)
        assets[f"{prefix}_missing"] = step_missing
    return assets, []


class EventViewer(QMainWindow):
    def __init__(self, assets: dict[str, Any]) -> None:
        super().__init__()
        self.setWindowTitle("Danbooru Event Explorer")
        self.resize(1440, 860)

        self.catalog = assets["tag_catalog.parquet"]
        self.category = assets["tag_category.parquet"]
        self.cooc_expr = assets["cooccurrence_event_expression.parquet"]
        self.cooc_cloth = assets["cooccurrence_event_clothing.parquet"]
        self.cooc_color = assets["cooccurrence_event_color.parquet"]
        self.rules = assets["dependency_rules.parquet"]
        self.metrics = assets["quality_metrics.json"]

        self.mats = assets.get("step3::event_min_ancestor_set.parquet")
        self.nav_edges = assets.get("step3::event_navigation_edges.parquet")
        self.event_prompt = assets.get("step3::event_prompt_only.parquet")
        self.step3_metrics = assets.get("step3::step3_metrics.json")
        self.step3_missing = assets.get("step3_missing", [])

        self.group_mapping = assets.get("step7::event_group_mapping.json")
        self.taxonomy = assets.get("step7::event_taxonomy.parquet")
        self.step7_missing = assets.get("step7_missing", [])
        self.taxonomy_step9 = assets.get("step9::event_taxonomy_enriched.parquet")
        self.step9_summary = assets.get("step9::activity_subcategory_summary.json")
        self.step9_missing = assets.get("step9_missing", [])
        self.subcategory_ko_map = assets.get("step10::subcategory_display_ko.json", {})
        self.taxonomy_step10_v2_1 = assets.get("step10::event_taxonomy_v2_1.parquet")
        self.taxonomy_step10 = assets.get("step10::event_taxonomy_v2.parquet")
        self.step10_summary_v2_1 = assets.get("step10::activity_subcategory_v2_1_summary.json")
        self.step10_summary = assets.get("step10::activity_subcategory_v2_summary.json")
        self.step10_missing = assets.get("step10_missing", [])

        self.id_to_tag = dict(zip(self.catalog["tag_id"], self.catalog["tag_name"]))
        self.events = self.category[self.category["is_event"] == True].copy().sort_values("tag_name")
        self.event_name_to_id = dict(zip(self.events["tag_name"], self.events["tag_id"]))

        self.root_anc_map: dict[str, set[str]] = {}
        self.all_anc_map: dict[str, set[str]] = {}
        self.event_combo_index: dict[str, Counter[tuple[str, ...]]] = {}
        self.event_post_count_map: dict[str, int] = {}
        self.event_post_count_rank_map: dict[str, int] = {}

        self.search_blob_map: dict[str, str] = {}
        self.group_display_map: dict[str, str] = {}
        self.subgroup_display_map: dict[str, str] = {}
        self.activity_subcategory_display_map: dict[str, str] = {}
        self.subcategory_display_map: dict[str, str] = {}
        self.tree_event_items: dict[str, QTreeWidgetItem] = {}

        self.current_event: str = ""
        self.current_rating: str = "General"
        self._sync_selection = False

        self._prepare_step3_indexes()
        self._prepare_taxonomy_indexes()

        self.rating_character_map = self._build_rating_character_map()

        self.search_input = QLineEdit()
        self.rating_button_group = QButtonGroup(self)
        self.rating_button_group.setExclusive(True)
        self.rating_buttons: dict[str, QPushButton] = {}
        self.character_combo = QComboBox()
        self.top5_only_checkbox = QCheckBox("Activity 상위 5개 서브카테고리만 표시")
        self.top5_only_checkbox.setChecked(True)
        self.event_tree = QTreeWidget()
        self.event_list = QListWidget()

        self.title_label = QLabel("Select an event")
        self.reason_label = QLabel("근거: -")
        self.reason_label.setStyleSheet("color: #B0B4BC; font-size: 11px;")
        self.expr_table = self._new_table(["Expression", "Count", "Confidence", "PMI"])
        self.cloth_table = self._new_table(["Clothing", "Count", "Confidence", "PMI"])
        self.color_table = self._new_table(["Color", "Count", "Confidence", "PMI"])
        self.dep_table = self._new_table(["Child", "Parent", "Type", "Support", "Confidence"])
        self.nav_table = self._new_table(["Target", "EdgeType", "Support", "Confidence", "Jaccard"])
        self.combo_table = self._new_table(
            [
                "Observed Event Combo",
                "Count",
                "Retained Dependencies (Expr/Cloth > 0.9)",
                "Shared Root Ancestors",
                "CommonRootN",
            ]
        )

        self.nav_info = QTextEdit()
        self.nav_info.setReadOnly(True)
        self.combo_info = QTextEdit()
        self.combo_info.setReadOnly(True)
        self.metrics_box = QTextEdit()
        self.metrics_box.setReadOnly(True)

        self._build_ui()
        self._render_quality()
        self._apply_filter("")

    def _build_rating_character_map(self) -> dict[str, list[tuple[str, int]]]:
        counts: dict[str, dict[str, int]] = {}
        zf = open_data_zip()
        if _zexists(zf, "partition_row_counts.json"):
            try:
                counts = _zread_json(zf, "partition_row_counts.json")
            except Exception:
                counts = {}
        out: dict[str, list[tuple[str, int]]] = {}
        for rating in RATING_TOGGLES:
            rating_counts = counts.get(rating, {})
            items: list[tuple[str, int]] = []
            for key in PERSON_PARTITION_ORDER:
                items.append((key, int(rating_counts.get(key, 0))))
            out[rating] = items
        return out

    @staticmethod
    def _format_partition_item(partition_key: str, row_count: int) -> str:
        label = PERSON_PARTITION_LABELS.get(partition_key, partition_key.replace("_", " "))
        return f"{label} ({row_count:,})"

    def _prepare_step3_indexes(self) -> None:
        if self.mats is not None:
            for row in self.mats.itertuples(index=False):
                tag = str(row.event_tag)
                self.root_anc_map[tag] = set(split_csv(row.minimal_root_ancestors))
                self.all_anc_map[tag] = set(split_csv(row.all_ancestors))
                self.event_post_count_map[tag] = int(row.post_count)

        if self.event_prompt is not None:
            combo_index: defaultdict[str, Counter[tuple[str, ...]]] = defaultdict(Counter)
            for tags_str in self.event_prompt["event_tags"].fillna("").astype(str):
                tags = tuple(sorted(set(split_csv(tags_str))))
                if not tags:
                    continue
                for event_tag in tags:
                    combo_index[event_tag][tags] += 1
            self.event_combo_index = dict(combo_index)

    def _prepare_taxonomy_indexes(self) -> None:
        if self.taxonomy_step10_v2_1 is not None and len(self.taxonomy_step10_v2_1) > 0:
            self.taxonomy = self.taxonomy_step10_v2_1
        if self.taxonomy_step10 is not None and len(self.taxonomy_step10) > 0:
            if self.taxonomy is None or len(self.taxonomy) == 0:
                self.taxonomy = self.taxonomy_step10
        if self.taxonomy_step9 is not None and len(self.taxonomy_step9) > 0:
            if self.taxonomy is None or len(self.taxonomy) == 0:
                self.taxonomy = self.taxonomy_step9
        if not isinstance(self.subcategory_ko_map, dict):
            self.subcategory_ko_map = {}
        merged_ko_map = default_subcategory_ko_map()
        merged_ko_map.update({str(k): str(v) for k, v in self.subcategory_ko_map.items()})
        self.subcategory_ko_map = merged_ko_map

        if self.group_mapping:
            for group, meta in self.group_mapping.get("groups", {}).items():
                label = str(meta.get("display_en", group))
                self.group_display_map[group] = label
            for subgroup, meta in self.group_mapping.get("subgroups", {}).items():
                label = str(meta.get("display_en", subgroup))
                self.subgroup_display_map[subgroup] = label

        if self.taxonomy is None or len(self.taxonomy) == 0:
            rows: list[dict[str, Any]] = []
            for event_name in self.events["tag_name"].astype(str).tolist():
                rows.append(
                    {
                        "event_tag": event_name,
                        "group": "expression action",
                        "group_order": 0,
                        "subgroup": "activity",
                        "subgroup_order": 0,
                        "post_count": int(self.event_post_count_map.get(event_name, 0)),
                        "root_ancestor_count": int(len(self.root_anc_map.get(event_name, set()))),
                        "search_blob": event_name,
                    }
                )
            self.taxonomy = pd.DataFrame(rows)

        self.taxonomy = self.taxonomy.copy()
        self.taxonomy["event_tag"] = self.taxonomy["event_tag"].astype(str)
        for col, default in [
            ("group", "expression action"),
            ("subgroup", "activity"),
            ("group_order", 0),
            ("subgroup_order", 0),
            ("post_count", 0),
            ("root_ancestor_count", 0),
            ("activity_subcategory", ""),
            ("activity_subcategory_order", 999),
        ]:
            if col not in self.taxonomy.columns:
                self.taxonomy[col] = default

        # Generalized subcategory: migrate activity_subcategory → subcategory
        if "subcategory" not in self.taxonomy.columns:
            self.taxonomy["subcategory"] = self.taxonomy["activity_subcategory"].astype(str)
        if "subcategory_order" not in self.taxonomy.columns:
            self.taxonomy["subcategory_order"] = self.taxonomy["activity_subcategory_order"]

        if "search_blob" not in self.taxonomy.columns:
            self.taxonomy["search_blob"] = self.taxonomy["event_tag"]

        self.taxonomy["group_order"] = pd.to_numeric(self.taxonomy["group_order"], errors="coerce").fillna(0).astype(int)
        self.taxonomy["subgroup_order"] = pd.to_numeric(self.taxonomy["subgroup_order"], errors="coerce").fillna(0).astype(int)
        self.taxonomy["post_count"] = pd.to_numeric(self.taxonomy["post_count"], errors="coerce").fillna(0).astype(int)
        self.taxonomy["root_ancestor_count"] = pd.to_numeric(self.taxonomy["root_ancestor_count"], errors="coerce").fillna(0).astype(int)
        self.taxonomy["activity_subcategory"] = self.taxonomy["activity_subcategory"].astype(str)
        self.taxonomy["activity_subcategory_order"] = pd.to_numeric(
            self.taxonomy["activity_subcategory_order"], errors="coerce"
        ).fillna(999).astype(int)
        self.taxonomy["subcategory"] = self.taxonomy["subcategory"].astype(str).replace("nan", "")
        self.taxonomy["subcategory_order"] = pd.to_numeric(
            self.taxonomy["subcategory_order"], errors="coerce"
        ).fillna(999).astype(int)

        for row in self.taxonomy.itertuples(index=False):
            event_tag = str(row.event_tag)
            self.search_blob_map[event_tag] = str(getattr(row, "search_blob", event_tag)).lower()
            self.event_post_count_rank_map[event_tag] = int(getattr(row, "post_count", 0) or 0)
            # Legacy: activity_subcategory display map
            subcat_key = str(getattr(row, "activity_subcategory", "") or "")
            if subcat_key and subcat_key not in self.activity_subcategory_display_map:
                en = pretty_subcategory_name(subcat_key)
                ko = self.subcategory_ko_map.get(subcat_key, "")
                self.activity_subcategory_display_map[subcat_key] = f"{en} ({ko})" if ko else en
            # Generalized: subcategory display map
            gen_subcat = str(getattr(row, "subcategory", "") or "")
            if gen_subcat and gen_subcat not in self.subcategory_display_map:
                en = pretty_subcategory_name(gen_subcat)
                ko = self.subcategory_ko_map.get(gen_subcat, "")
                self.subcategory_display_map[gen_subcat] = f"{en} ({ko})" if ko else en

    def _build_ui(self) -> None:
        root = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(root)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)

        left_layout.addWidget(QLabel(f"Event Tags ({len(self.events):,})"))

        rating_row = QWidget()
        rating_layout = QHBoxLayout(rating_row)
        rating_layout.setContentsMargins(0, 0, 0, 0)
        rating_layout.setSpacing(6)
        for rating in RATING_TOGGLES:
            btn = QPushButton(rating)
            btn.setCheckable(True)
            btn.setStyleSheet(
                "QPushButton { font-weight: 600; padding: 4px 10px; }"
                "QPushButton:checked { background-color: #2d6cdf; color: white; }"
            )
            self.rating_button_group.addButton(btn)
            self.rating_buttons[rating] = btn
            rating_layout.addWidget(btn)
        rating_layout.addStretch(1)
        self.rating_button_group.buttonToggled.connect(self._on_rating_toggled)
        self.rating_buttons["General"].setChecked(True)
        left_layout.addWidget(rating_row)

        self.character_combo.setEditable(False)
        self.character_combo.setMaxVisibleItems(13)
        self.character_combo.setToolTip("girl 6 -> boy 6 -> other 순서")
        self._refresh_character_combo()
        left_layout.addWidget(self.character_combo)

        self.search_input.setPlaceholderText("Search event / subgroup / KR desc")
        self.search_input.textChanged.connect(self._on_search_changed)
        left_layout.addWidget(self.search_input)
        toggle_row = QWidget()
        toggle_layout = QHBoxLayout(toggle_row)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.addWidget(self.top5_only_checkbox)
        toggle_layout.addStretch(1)
        self.top5_only_checkbox.stateChanged.connect(lambda _v: self._apply_filter(self.search_input.text()))
        left_layout.addWidget(toggle_row)

        self.event_tree.setColumnCount(3)
        self.event_tree.setHeaderLabels(["Group / Subgroup / Subcategory / Event", "Posts", "Roots"])
        self.event_tree.setUniformRowHeights(True)
        self.event_tree.setAlternatingRowColors(True)
        self.event_tree.itemSelectionChanged.connect(self._on_tree_selected)
        header = self.event_tree.header()
        header.setStretchLastSection(False)
        header.resizeSection(0, 430)
        header.resizeSection(1, 90)
        header.resizeSection(2, 76)

        self.event_list.currentTextChanged.connect(self._on_list_selected)

        left_tabs = QTabWidget()
        left_tabs.addTab(self.event_tree, "Tree")
        left_tabs.addTab(self.event_list, "List")
        left_layout.addWidget(left_tabs)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)
        self.title_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        right_layout.addWidget(self.title_label)
        right_layout.addWidget(self.reason_label)

        tabs = QTabWidget()
        tabs.addTab(self.expr_table, "Expression")
        tabs.addTab(self.cloth_table, "Clothing")
        tabs.addTab(self.color_table, "Color")
        tabs.addTab(self.dep_table, "Dependencies")

        nav_widget = QWidget()
        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.addWidget(self.nav_info)
        nav_layout.addWidget(self.nav_table)
        tabs.addTab(nav_widget, "Navigation")

        combo_widget = QWidget()
        combo_layout = QVBoxLayout(combo_widget)
        combo_layout.setContentsMargins(0, 0, 0, 0)
        combo_layout.addWidget(self.combo_info)
        combo_layout.addWidget(self.combo_table)
        tabs.addTab(combo_widget, "Observed Combos")

        tabs.addTab(self.metrics_box, "Quality")
        right_layout.addWidget(tabs)

        root.addWidget(left)
        root.addWidget(right)
        root.setStretchFactor(0, 2)
        root.setStretchFactor(1, 3)

    @staticmethod
    def _new_table(headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    @staticmethod
    def _set_number(table: QTableWidget, row: int, col: int, value: float | int) -> None:
        item = QTableWidgetItem()
        item.setData(Qt.ItemDataRole.DisplayRole, value)
        item.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        table.setItem(row, col, item)

    def _on_search_changed(self, text: str) -> None:
        self._apply_filter(text)

    def _on_rating_toggled(self, button: QPushButton, checked: bool) -> None:
        if not checked:
            return
        rating = button.text().strip()
        if rating not in self.rating_character_map:
            return
        self.current_rating = rating
        self._refresh_character_combo()

    def _refresh_character_combo(self) -> None:
        items = self.rating_character_map.get(self.current_rating, [])
        self.character_combo.blockSignals(True)
        self.character_combo.clear()
        for partition_key, row_count in items:
            self.character_combo.addItem(
                self._format_partition_item(partition_key, row_count),
                userData=partition_key,
            )
        self.character_combo.blockSignals(False)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        all_events = self.events["tag_name"].astype(str).tolist()
        filtered_events = [name for name in all_events if self._matches_search(name, needle)]
        if needle and filtered_events:
            def match_mode(name: str) -> int:
                lname = str(name).lower()
                if lname == needle:
                    return 0
                if lname.startswith(needle):
                    return 1
                if needle in lname:
                    return 2
                return 3

            filtered_events = sorted(
                filtered_events,
                key=lambda n: (
                    match_mode(str(n)),
                    -int(self.event_post_count_rank_map.get(str(n), 0)),
                    str(n),
                ),
            )

        self._refresh_event_list(filtered_events)
        self._refresh_event_tree(filtered_events)

        if filtered_events:
            if self.current_event in filtered_events:
                self._select_event(self.current_event, source="filter")
            else:
                self._select_event(filtered_events[0], source="filter")
        else:
            self.current_event = ""
            self.title_label.setText("No matched events")
            self.reason_label.setText("근거: -")
            self._clear_detail_views()

    def _matches_search(self, event_name: str, needle: str) -> bool:
        if not needle:
            return True
        blob = self.search_blob_map.get(event_name, event_name.lower())
        return needle in blob

    def _refresh_event_list(self, filtered_events: list[str]) -> None:
        self.event_list.blockSignals(True)
        self.event_list.clear()
        self.event_list.addItems(filtered_events)
        self.event_list.blockSignals(False)

    def _refresh_event_tree(self, filtered_events: list[str]) -> None:
        self.tree_event_items = {}
        filtered_set = set(filtered_events)

        df = self.taxonomy[self.taxonomy["event_tag"].isin(filtered_set)].copy()
        df = df.sort_values(
            ["group_order", "group", "subgroup_order", "subgroup", "post_count", "event_tag"],
            ascending=[True, True, True, True, False, True],
        )

        self.event_tree.blockSignals(True)
        self.event_tree.clear()

        for group_name, group_df in df.groupby("group", sort=False):
            group_item = QTreeWidgetItem()
            group_label = self.group_display_map.get(group_name, group_name.title())
            group_item.setText(0, f"{group_label} ({len(group_df):,})")
            group_item.setText(1, f"{len(group_df):,}")
            group_item.setTextAlignment(1, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            group_item.setData(0, ROLE_LEVEL, "group")
            self.event_tree.addTopLevelItem(group_item)

            for subgroup_name, subgroup_df in group_df.groupby("subgroup", sort=False):
                subgroup_item = QTreeWidgetItem()
                subgroup_label = self.subgroup_display_map.get(subgroup_name, subgroup_name)
                subgroup_item.setText(0, f"{subgroup_label} ({len(subgroup_df):,})")
                subgroup_item.setText(1, f"{len(subgroup_df):,}")
                subgroup_item.setTextAlignment(1, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                subgroup_item.setData(0, ROLE_LEVEL, "subgroup")
                group_item.addChild(subgroup_item)

                has_subcat = (
                    "subcategory" in subgroup_df.columns
                    and subgroup_df["subcategory"].astype(str).str.strip().str.len().gt(0).any()
                )

                if has_subcat:
                    subcat_df = subgroup_df.sort_values(
                        ["subcategory_order", "subcategory", "post_count", "event_tag"],
                        ascending=[True, True, False, True],
                    )
                    if self.top5_only_checkbox.isChecked():
                        subcat_counts = (
                            subcat_df.groupby("subcategory")
                            .size()
                            .sort_values(ascending=False)
                        )
                        top_keys = set(subcat_counts.head(5).index.astype(str).tolist())
                        subcat_df = subcat_df[subcat_df["subcategory"].astype(str).isin(top_keys)]

                    for subcat_name, subcat_group_df in subcat_df.groupby("subcategory", sort=False):
                        label = self.subcategory_display_map.get(
                            str(subcat_name), pretty_subcategory_name(str(subcat_name))
                        )
                        subcat_item = QTreeWidgetItem()
                        subcat_item.setText(0, f"{label} ({len(subcat_group_df):,})")
                        subcat_item.setText(1, f"{len(subcat_group_df):,}")
                        subcat_item.setTextAlignment(1, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                        subcat_item.setData(0, ROLE_LEVEL, "subcategory")
                        subgroup_item.addChild(subcat_item)

                        for row in subcat_group_df.itertuples(index=False):
                            event_name = str(row.event_tag)
                            post_count = int(row.post_count)
                            root_count = int(row.root_ancestor_count)
                            item = QTreeWidgetItem()
                            item.setText(0, event_name)
                            item.setText(1, f"{post_count:,}")
                            item.setText(2, f"{root_count}")
                            item.setTextAlignment(1, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                            item.setTextAlignment(2, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                            item.setData(0, ROLE_LEVEL, "event")
                            item.setData(0, ROLE_EVENT, event_name)

                            combo_count = int(sum(self.event_combo_index.get(event_name, Counter()).values()))
                            if combo_count > 0:
                                font = QFont(item.font(0))
                                font.setBold(True)
                                item.setFont(0, font)

                            subcat_item.addChild(item)
                            self.tree_event_items[event_name] = item
                else:
                    for row in subgroup_df.itertuples(index=False):
                        event_name = str(row.event_tag)
                        post_count = int(row.post_count)
                        root_count = int(row.root_ancestor_count)

                        item = QTreeWidgetItem()
                        item.setText(0, event_name)
                        item.setText(1, f"{post_count:,}")
                        item.setText(2, f"{root_count}")
                        item.setTextAlignment(1, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                        item.setTextAlignment(2, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                        item.setData(0, ROLE_LEVEL, "event")
                        item.setData(0, ROLE_EVENT, event_name)

                        combo_count = int(sum(self.event_combo_index.get(event_name, Counter()).values()))
                        if combo_count > 0:
                            font = QFont(item.font(0))
                            font.setBold(True)
                            item.setFont(0, font)

                        subgroup_item.addChild(item)
                        self.tree_event_items[event_name] = item

        # Expand groups and subgroups; for subgroups with subcategory children,
        # expand one more level to reveal subcategory items (but keep events collapsed).
        for gi in range(self.event_tree.topLevelItemCount()):
            group_item = self.event_tree.topLevelItem(gi)
            group_item.setExpanded(True)
            for si in range(group_item.childCount()):
                subgroup_item = group_item.child(si)
                subgroup_item.setExpanded(True)
                # Check if first child is a subcategory (not an event)
                if subgroup_item.childCount() > 0:
                    first_child = subgroup_item.child(0)
                    if first_child.data(0, ROLE_LEVEL) == "subcategory":
                        # Subcategory items stay collapsed (events hidden)
                        for ci in range(subgroup_item.childCount()):
                            subgroup_item.child(ci).setExpanded(False)
                    else:
                        # Direct events: collapse the subgroup to hide them
                        subgroup_item.setExpanded(False)
        self.event_tree.blockSignals(False)

    def _on_list_selected(self, event_name: str) -> None:
        if not event_name or self._sync_selection:
            return
        self._select_event(event_name, source="list")

    def _on_tree_selected(self) -> None:
        if self._sync_selection:
            return
        item = self.event_tree.currentItem()
        if item is None:
            return
        if item.data(0, ROLE_LEVEL) != "event":
            return
        event_name = str(item.data(0, ROLE_EVENT) or "")
        if event_name:
            self._select_event(event_name, source="tree")

    def _select_event(self, event_name: str, source: str) -> None:
        if not event_name:
            return

        self._sync_selection = True
        try:
            self.current_event = event_name

            if source != "list":
                matches = self.event_list.findItems(event_name, Qt.MatchFlag.MatchExactly)
                if matches:
                    self.event_list.setCurrentItem(matches[0])

            if source != "tree":
                tree_item = self.tree_event_items.get(event_name)
                if tree_item is not None:
                    self.event_tree.setCurrentItem(tree_item)
        finally:
            self._sync_selection = False

        self._on_event_selected(event_name)

    def _clear_detail_views(self) -> None:
        for table in [
            self.expr_table,
            self.cloth_table,
            self.color_table,
            self.dep_table,
            self.nav_table,
            self.combo_table,
        ]:
            table.setRowCount(0)
        self.nav_info.setPlainText("")
        self.combo_info.setPlainText("")

    @staticmethod
    def _shorten_reason_text(text: str, limit: int = 140) -> str:
        value = " ".join(str(text or "").split())
        if len(value) <= limit:
            return value
        return value[: limit - 3] + "..."

    def _on_event_selected(self, event_name: str) -> None:
        if not event_name:
            return
        event_id = self.event_name_to_id.get(event_name)
        if event_id is None:
            return

        path_text = ""
        row = self.taxonomy[self.taxonomy["event_tag"] == event_name]
        if len(row) > 0:
            r = row.iloc[0]
            group_name = str(r.get("group", ""))
            subgroup_name = str(r.get("subgroup", ""))
            subcategory_name = str(r.get("activity_subcategory", ""))
            group_label = self.group_display_map.get(group_name, group_name)
            subgroup_label = self.subgroup_display_map.get(subgroup_name, subgroup_name)
            path_text = f" | {group_label} > {subgroup_label}"
            if subgroup_name == "activity" and subcategory_name:
                subcategory_label = self.activity_subcategory_display_map.get(
                    subcategory_name, pretty_subcategory_name(subcategory_name)
                )
                path_text = f"{path_text} > {subcategory_label}"

            method = str(r.get("activity_subcategory_method", "") or "")
            top_groups = str(r.get("top_parent_groups", "") or "")
            roots = str(r.get("minimal_root_ancestors", "") or "")
            reason_parts: list[str] = []
            if method:
                reason_parts.append(f"method={method}")
            if top_groups:
                reason_parts.append(f"context={self._shorten_reason_text(top_groups, 70)}")
            if roots:
                reason_parts.append(f"roots={self._shorten_reason_text(roots, 50)}")
            if not reason_parts and subgroup_name == "activity" and subcategory_name:
                reason_parts.append(f"subcategory={subcategory_name}")
            self.reason_label.setText("근거: " + (" | ".join(reason_parts) if reason_parts else "-"))
        else:
            self.reason_label.setText("근거: -")

        self.title_label.setText(f"Event: {event_name} (tag_id={int(event_id)}){path_text}")
        self._fill_cooccurrence(self.expr_table, self.cooc_expr, "event_tag_id", "expr_tag_id", int(event_id))
        self._fill_cooccurrence(self.cloth_table, self.cooc_cloth, "event_tag_id", "cloth_tag_id", int(event_id))
        self._fill_cooccurrence(self.color_table, self.cooc_color, "event_tag_id", "color_tag_id", int(event_id))
        self._fill_dependencies(event_name)
        self._fill_navigation(event_name)
        self._fill_observed_combos(event_name)

    def _fill_cooccurrence(
        self,
        table: QTableWidget,
        df: pd.DataFrame,
        event_col: str,
        target_col: str,
        event_id: int,
    ) -> None:
        sub = df[df[event_col] == event_id].sort_values("count", ascending=False).head(TOP_N)
        table.setSortingEnabled(False)
        table.setRowCount(len(sub))
        for row_idx, (_, row) in enumerate(sub.iterrows()):
            target_name = self.id_to_tag.get(int(row[target_col]), str(row[target_col]))
            table.setItem(row_idx, 0, QTableWidgetItem(target_name))
            self._set_number(table, row_idx, 1, int(row["count"]))
            self._set_number(table, row_idx, 2, round(float(row["confidence"]), 4))
            self._set_number(table, row_idx, 3, round(float(row["pmi"]), 4))
        table.setSortingEnabled(True)

    def _fill_dependencies(self, event_name: str) -> None:
        sub = self.rules[
            (self.rules["child_tag"] == event_name) | (self.rules["parent_tag"] == event_name)
        ].sort_values(["support", "confidence"], ascending=[False, False]).head(TOP_N)
        self.dep_table.setSortingEnabled(False)
        self.dep_table.setRowCount(len(sub))
        for row_idx, (_, row) in enumerate(sub.iterrows()):
            self.dep_table.setItem(row_idx, 0, QTableWidgetItem(str(row["child_tag"])))
            self.dep_table.setItem(row_idx, 1, QTableWidgetItem(str(row["parent_tag"])))
            self.dep_table.setItem(row_idx, 2, QTableWidgetItem(str(row["rule_type"])))
            self._set_number(self.dep_table, row_idx, 3, int(row["support"]))
            self._set_number(self.dep_table, row_idx, 4, round(float(row["confidence"]), 4))
        self.dep_table.setSortingEnabled(True)

    def _fill_navigation(self, event_name: str) -> None:
        if self.mats is None or self.nav_edges is None:
            missing_info = ", ".join(self.step3_missing) if self.step3_missing else "unknown"
            self.nav_info.setPlainText(
                "Step3 artifacts are not available.\n"
                f"missing: {missing_info}\n"
                f"path: {BASE_DIR}"
            )
            self.nav_table.setRowCount(0)
            return

        row = self.mats[self.mats["event_tag"] == event_name]
        if len(row) == 0:
            info_lines = [f"event: {event_name}", "MATS info not found"]
        else:
            r = row.iloc[0]
            roots = split_csv(r["minimal_root_ancestors"])
            info_lines = [
                f"event: {event_name}",
                f"post_count: {int(r['post_count'])}",
                f"depth: {int(r['depth'])}",
                f"immediate_parents: {r['immediate_parents'] or '-'}",
                f"minimal_parent_set: {r['minimal_parent_set'] or '-'}",
                f"minimal_root_ancestors: {r['minimal_root_ancestors'] or '-'}",
                f"common_ancestor_count(root): {len(roots)}",
                f"prompt_seed_tags: {r['prompt_seed_tags'] or '-'}",
            ]
        self.nav_info.setPlainText("\n".join(info_lines))

        nav_sub = self.nav_edges[self.nav_edges["source_tag"] == event_name].sort_values(
            ["edge_type", "support", "jaccard"], ascending=[True, False, False]
        ).head(TOP_N)
        self.nav_table.setSortingEnabled(False)
        self.nav_table.setRowCount(len(nav_sub))
        for row_idx, (_, row) in enumerate(nav_sub.iterrows()):
            self.nav_table.setItem(row_idx, 0, QTableWidgetItem(str(row["target_tag"])))
            self.nav_table.setItem(row_idx, 1, QTableWidgetItem(str(row["edge_type"])))
            self._set_number(self.nav_table, row_idx, 2, int(row["support"]))
            self._set_number(self.nav_table, row_idx, 3, round(float(row["confidence"]), 4))
            self._set_number(self.nav_table, row_idx, 4, round(float(row["jaccard"]), 4))
        self.nav_table.setSortingEnabled(True)

    def _fill_observed_combos(self, event_name: str) -> None:
        if self.event_prompt is None or not self.event_combo_index:
            self.combo_info.setPlainText(
                "Step3 event_prompt_only.parquet is not available."
            )
            self.combo_table.setRowCount(0)
            return

        counter = self.event_combo_index.get(event_name, Counter())
        total_posts = int(sum(counter.values()))
        unique_combos = int(len(counter))
        self_count = int(self.event_post_count_map.get(event_name, total_posts))
        event_id = self.event_name_to_id.get(event_name)
        retained_expr, retained_cloth = self._get_retained_dependency_tags(int(event_id)) if event_id else ([], [])
        retained_chunks: list[str] = []
        if retained_expr:
            retained_chunks.append("expr: " + ", ".join(retained_expr))
        if retained_cloth:
            retained_chunks.append("cloth: " + ", ".join(retained_cloth))
        retained_text = " | ".join(retained_chunks) if retained_chunks else "-"

        shared_root_counter: Counter[str] = Counter()
        combo_rows: list[tuple[tuple[str, ...], int, set[str]]] = []
        for combo, count in counter.most_common(TOP_N):
            root_sets = [self.root_anc_map.get(tag, set()) for tag in combo]
            if root_sets:
                shared_roots = set.intersection(*root_sets) if all(root_sets) else set()
            else:
                shared_roots = set()
            if shared_roots:
                for root in shared_roots:
                    shared_root_counter[root] += count
            combo_rows.append((combo, count, shared_roots))

        shared_top = shared_root_counter.most_common(10)
        summary_lines = [
            f"event: {event_name}",
            f"posts_with_event: {self_count:,}",
            f"observed_combo_rows: {total_posts:,}",
            f"unique_observed_combos: {unique_combos:,}",
            (
                f"retained_dependencies(expr/cloth, confidence>{OBSERVED_RETAIN_CONFIDENCE_GT}): "
                f"{len(retained_expr) + len(retained_cloth)}"
            ),
        ]
        if shared_top:
            summary_lines.append("top_common_root_ancestors:")
            for tag, cnt in shared_top:
                summary_lines.append(f"- {tag}: {cnt:,}")
        else:
            summary_lines.append("top_common_root_ancestors: (none)")
        self.combo_info.setPlainText("\n".join(summary_lines))

        self.combo_table.setSortingEnabled(False)
        self.combo_table.setRowCount(len(combo_rows))
        for row_idx, (combo, count, shared_roots) in enumerate(combo_rows):
            self.combo_table.setItem(row_idx, 0, QTableWidgetItem(", ".join(combo)))
            self._set_number(self.combo_table, row_idx, 1, int(count))
            self.combo_table.setItem(row_idx, 2, QTableWidgetItem(retained_text))
            self.combo_table.setItem(row_idx, 3, QTableWidgetItem(join_csv(shared_roots) or "-"))
            self._set_number(self.combo_table, row_idx, 4, int(len(shared_roots)))
        self.combo_table.setSortingEnabled(True)

    def _get_retained_dependency_tags(self, event_id: int) -> tuple[list[str], list[str]]:
        if event_id <= 0:
            return [], []

        expr_sub = self.cooc_expr[
            (self.cooc_expr["event_tag_id"] == event_id)
            & (pd.to_numeric(self.cooc_expr["confidence"], errors="coerce") > OBSERVED_RETAIN_CONFIDENCE_GT)
        ].sort_values(["count", "confidence"], ascending=[False, False]).head(OBSERVED_RETAIN_TOP_N)
        cloth_sub = self.cooc_cloth[
            (self.cooc_cloth["event_tag_id"] == event_id)
            & (pd.to_numeric(self.cooc_cloth["confidence"], errors="coerce") > OBSERVED_RETAIN_CONFIDENCE_GT)
        ].sort_values(["count", "confidence"], ascending=[False, False]).head(OBSERVED_RETAIN_TOP_N)

        expr_tags = [
            self.id_to_tag.get(int(tag_id), str(tag_id))
            for tag_id in expr_sub["expr_tag_id"].dropna().astype(int).tolist()
        ]
        cloth_tags = [
            self.id_to_tag.get(int(tag_id), str(tag_id))
            for tag_id in cloth_sub["cloth_tag_id"].dropna().astype(int).tolist()
        ]
        return expr_tags, cloth_tags

    def _render_quality(self) -> None:
        lines: list[str] = []
        lines.append("[step1]")
        lines.append(f"post_count: {self.metrics.get('post_count', 0):,}")
        lines.append(f"unique_tags: {self.metrics.get('unique_tags', 0):,}")
        lines.append("")
        lines.append("[coverage]")
        for key, value in self.metrics.get("coverage", {}).items():
            lines.append(f"- {key}: {float(value):.4f}")
        lines.append("")
        lines.append("[precision_proxy]")
        for key, value in self.metrics.get("precision_proxy", {}).items():
            lines.append(f"- {key}: {float(value):.4f}")

        if self.step3_metrics is not None:
            lines.append("")
            lines.append("[step3]")
            lines.append(f"event_vocab_size: {int(self.step3_metrics.get('event_vocab_size', 0)):,}")
            lines.append(
                f"non_empty_event_posts: {int(self.step3_metrics.get('non_empty_event_posts', 0)):,}"
            )
            lines.append(
                f"events_with_any_ancestors: {int(self.step3_metrics.get('events_with_any_ancestors', 0)):,}"
            )
            lines.append(
                f"events_with_root_ancestors: {int(self.step3_metrics.get('events_with_root_ancestors', 0)):,}"
            )
            lines.append(
                f"unique_root_ancestors: {int(self.step3_metrics.get('unique_root_ancestors', 0)):,}"
            )
            lines.append(
                f"avg_event_count_per_post: {float(self.step3_metrics.get('avg_event_count_per_post', 0.0)):.4f}"
            )
            lines.append(
                f"avg_seed_count_per_post: {float(self.step3_metrics.get('avg_seed_count_per_post', 0.0)):.4f}"
            )

        lines.append("")
        lines.append("[step7]")
        if self.group_mapping is not None:
            meta = self.group_mapping.get("meta", {})
            lines.append(f"event_count: {int(meta.get('event_count', 0)):,}")
            lines.append(f"groups: {int(meta.get('groups', 0))}")
            lines.append(f"subgroups: {int(meta.get('subgroups', 0))}")
            cov = meta.get("source_coverage_ratio", {})
            if isinstance(cov, dict):
                for key, value in cov.items():
                    lines.append(f"- {key}: {float(value):.4f}")
        else:
            missing_info = ", ".join(self.step7_missing) if self.step7_missing else "unknown"
            lines.append(f"missing: {missing_info}")

        lines.append("")
        lines.append("[step9]")
        if self.step9_summary is not None:
            lines.append(f"activity_event_count: {int(self.step9_summary.get('activity_event_count', 0)):,}")
            lines.append(
                f"holding_related_activity_count: {int(self.step9_summary.get('holding_related_activity_count', 0)):,}"
            )
            counts = self.step9_summary.get("subcategory_counts", {})
            if isinstance(counts, dict):
                for key, value in sorted(counts.items(), key=lambda kv: (-int(kv[1]), str(kv[0]))):
                    lines.append(f"- {key}: {int(value):,}")
        else:
            missing_info = ", ".join(self.step9_missing) if self.step9_missing else "unknown"
            lines.append(f"missing: {missing_info}")

        lines.append("")
        lines.append("[step10]")
        if self.step10_summary_v2_1 is not None:
            base = self.step10_summary_v2_1.get("base_summary", {})
            lines.append(
                f"activity_other: {int(base.get('activity_other_before', 0))} -> {int(self.step10_summary_v2_1.get('activity_other_after', 0))}"
            )
            lines.append(
                f"holding_misc: {int(base.get('holding_misc_before', 0))} -> {int(self.step10_summary_v2_1.get('holding_misc_after', 0))}"
            )
            lines.append(
                f"override_applied_count: {int(self.step10_summary_v2_1.get('override_applied_count', 0)):,}"
            )
            lines.append(
                f"override_changed_count: {int(self.step10_summary_v2_1.get('override_changed_count', 0)):,}"
            )
        elif self.step10_summary is not None:
            lines.append(
                f"activity_other: {int(self.step10_summary.get('activity_other_before', 0))} -> {int(self.step10_summary.get('activity_other_after', 0))}"
            )
            lines.append(
                f"holding_misc: {int(self.step10_summary.get('holding_misc_before', 0))} -> {int(self.step10_summary.get('holding_misc_after', 0))}"
            )
            lines.append(f"reclassified_count: {int(self.step10_summary.get('reclassified_count', 0)):,}")
        elif self.subcategory_ko_map:
            lines.append(f"subcategory_ko_labels: {len(self.subcategory_ko_map):,}")
        else:
            missing_info = ", ".join(self.step10_missing) if self.step10_missing else "unknown"
            lines.append(f"missing: {missing_info}")

        self.metrics_box.setPlainText("\n".join(lines))



_PREFIX_TO_RATING: dict[str, str] = {v: k for k, v in RATING_PREFIX_MAP.items()}
_RATING_SHORT = {"g": "G", "s": "S", "q": "Q", "e": "E"}

_ROLE_HTML = Qt.ItemDataRole.UserRole + 100

_RATING_BADGE_COLORS: dict[str, str] = {
    "S": "#6BB8E8",  # sky blue (하늘색)
    "Q": "#E8A838",  # light orange (연주황색)
    "E": "#E07020",  # orange (주황색)
}


def _format_switch_item_html(rating_short: str, person_label: str, count_str: str) -> str:
    """Build HTML with colored rating badge: <span color>[S]</span> 1girl solo (315k)."""
    color = _RATING_BADGE_COLORS.get(rating_short)
    if color:
        badge = f'<span style="color:{color};font-weight:bold">[{rating_short}]</span>'
    else:
        badge = f'<span style="color:#CCC">[{rating_short}]</span>'
    return f'{badge}<span style="color:#CCC"> {person_label} ({count_str})</span>'


class _RichComboDelegate(QStyledItemDelegate):
    """Item delegate that renders HTML text in QComboBox popup items."""

    def paint(self, painter, option, index):  # noqa: N802
        self.initStyleOption(option, index)
        style = option.widget.style() if option.widget else QApplication.style()

        # Suppress default text drawing; we render HTML ourselves
        option.text = ""
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget,
        )

        html = index.data(_ROLE_HTML)
        if not html:
            # Fallback: plain text
            painter.save()
            painter.setPen(option.palette.text().color())
            painter.drawText(
                option.rect.adjusted(4, 0, 0, 0),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                index.data(Qt.ItemDataRole.DisplayRole) or "",
            )
            painter.restore()
            return

        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setHtml(html)

        painter.save()
        y_offset = max(0, (option.rect.height() - doc.size().height()) / 2)
        painter.translate(option.rect.left() + 4, option.rect.top() + y_offset)
        doc.drawContents(painter)
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802
        hint = super().sizeHint(option, index)
        return QSize(hint.width(), max(hint.height(), 20))


_PERSON_TAG_MAP: dict[str, list[str]] = {
    "1girl_solo": ["1girl", "solo"],
    "1boy_solo": ["1boy", "solo"],
    "1girl_1boy": ["1girl", "1boy"],
    "2girls": ["2girls"],
    "2boys": ["2boys"],
    "1girl_multiple_boys": ["1girl", "multiple boys"],
    "1boy_multiple_girls": ["1boy", "multiple girls"],
    "multiple_girls": ["multiple girls"],
    "multiple_boys": ["multiple boys"],
    "multiple_girls_multiple_boys": ["multiple girls", "multiple boys"],
    "1girl": ["1girl"],
    "1boy": ["1boy"],
    "other": [],
}

_RATING_TAG_MAP: dict[str, str] = {
    "General": "general",
    "Sensitive": "sensitive",
    "Question": "questionable",
    "Explicit": "explicit",
}


def _load_recommendations() -> dict[str, dict]:
    """Load event_recommended_tags.json from data.zip."""
    zf = open_data_zip()
    if not _zexists(zf, "event_recommended_tags.json"):
        return {}
    try:
        data = _zread_json(zf, "event_recommended_tags.json")
        return data.get("recommendations", {})
    except Exception:
        return {}


def _load_event_partition_index() -> dict[str, list]:
    """Load event_partition_index.json from data.zip."""
    zf = open_data_zip()
    if not _zexists(zf, "event_partition_index.json"):
        return {}
    try:
        return _zread_json(zf, "event_partition_index.json")
    except Exception:
        return {}


def _parse_partition_name(partition_name: str) -> tuple[str, str]:
    """Split 'g_1girl_solo' → ('g', '1girl_solo')."""
    idx = partition_name.index("_")
    return partition_name[:idx], partition_name[idx + 1:]


def _format_count(n: int) -> str:
    """315444 -> '315k', 1258076 -> '1,258k', 150 -> '150'."""
    if n >= 1000:
        return f"{n // 1000:,}k"
    return str(n)


def _discover_step15_partitions() -> set[str]:
    required = {
        "event_observed_combo.parquet",
        "event_expression_cooccurrence.parquet",
        "event_clothing_cooccurrence.parquet",
        "event_characteristic_cooccurrence.parquet",
        "quality_metrics_step15.json",
    }
    zf = open_data_zip()
    # Scan ZIP entries: partitions/{name}/{file}
    partition_files: dict[str, set[str]] = {}
    for entry in zf.namelist():
        if not entry.startswith("partitions/"):
            continue
        parts = entry.split("/")
        if len(parts) >= 3:
            partition_files.setdefault(parts[1], set()).add(parts[2])
    return {name for name, files in partition_files.items() if required <= files}


def _norm_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower().replace("_", " ")
    return " ".join(text.split())


def _load_color_prefixes() -> list[str]:
    zf = open_data_zip()
    if not _zexists(zf, "color.txt"):
        return []
    out: set[str] = set()
    for line in _zread_text(zf, "color.txt").splitlines():
        value = _norm_text(line)
        if value:
            out.add(value)
    return sorted(out, key=len, reverse=True)


class PartitionBoundViewer(EventViewer):
    def __init__(self, assets: dict[str, Any]) -> None:
        self.step15_cache: dict[str, dict[str, Any]] = {}
        self.step15_available_partitions: set[str] = set()
        self.step15_active_partition_name = ""
        self.step15_active_data: dict[str, Any] | None = None
        self.step15_event_count_map: dict[str, int] = {}
        self.color_prefixes = _load_color_prefixes()
        self.staged_events: list[str] = []
        self.staged_combos_map: dict[str, list[tuple[frozenset[str], int]]] = {}
        self._event_pair_cache: set[frozenset[str]] | None = None
        self._recommendations = _load_recommendations()
        self._auto_dep_tags: list[str] = []           # dependency auto-insert tags
        self._active_rec_tags: dict[str, bool] = {}   # co-occurrence chip toggle state
        self._cooc_cache: dict[str, dict] = {}        # per-event co-occurrence cache
        self._refreshing_chips: bool = False           # guard against re-entrant chip refresh
        self._event_partition_index: dict[str, list] = _load_event_partition_index()
        self._switching_partition: bool = False
        self._step15_ready = False
        super().__init__(assets)
        self._base_taxonomy = self.taxonomy.copy()
        self._base_event_post_count_rank_map = dict(self.event_post_count_rank_map)
        self.setWindowTitle("Danbooru Event Explorer (Multi-Event Combo)")
        self._convert_color_tab_to_characteristic()

        self.character_combo.currentIndexChanged.connect(self._on_character_changed_step15)
        self._refresh_step15_partition_binding()
        self._step15_ready = True
        self._setup_staging_ui()
        self._optimize_ui_for_production()

    # ------------------------------------------------------------------
    # Production UI optimization
    # ------------------------------------------------------------------

    def _optimize_ui_for_production(self) -> None:
        # 1. Hide top5_only_checkbox and its parent toggle_row
        self.top5_only_checkbox.setVisible(False)
        toggle_parent = self.top5_only_checkbox.parentWidget()
        if toggle_parent and toggle_parent is not self:
            toggle_parent.setVisible(False)

        # 2. Hide reason_label and title_label
        self.reason_label.setVisible(False)
        self.title_label.setVisible(False)

        # 3. Hide Roots column (column 2) in tree
        self.event_tree.setColumnHidden(2, True)
        self.event_tree.setHeaderLabels(["Group / Subgroup / Event", "Posts", ""])

        # 4. Hide PMI column (column 3) and fix Confidence stretch
        for tbl in (self.expr_table, self.cloth_table, self.color_table):
            tbl.setColumnHidden(3, True)
            hdr = tbl.horizontalHeader()
            hdr.setStretchLastSection(False)
            hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        # 5. Add search clear button
        self._add_search_clear_button()

        # 6. Remove Dependencies, Navigation, Quality tabs; move Observed Combos first
        self._remove_debug_tabs()
        self._move_combos_tab_first()

        # 7. Simplify combo_table (2 columns, word wrap, hide combo_info)
        self._simplify_combo_tab()

        # 8. Add right panel (image + prompt + generate)
        self._add_right_panel()

        # 9. Connect combo_table selection → prompt generation
        self.combo_table.itemSelectionChanged.connect(self._on_combo_selected)

        # 10. Replace Tree/List tabs with master-detail splitter
        self._replace_tree_with_master_detail()

    def _add_search_clear_button(self) -> None:
        parent_widget = self.search_input.parentWidget()
        if parent_widget is None:
            return
        parent_layout = parent_widget.layout()
        if parent_layout is None:
            return

        idx = parent_layout.indexOf(self.search_input)
        parent_layout.removeWidget(self.search_input)

        search_row = QWidget()
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(4)
        search_layout.addWidget(self.search_input)

        clear_btn = QPushButton("\u2715")
        clear_btn.setFixedWidth(28)
        clear_btn.setToolTip("Clear search")
        clear_btn.clicked.connect(lambda: self.search_input.clear())
        search_layout.addWidget(clear_btn)

        parent_layout.insertWidget(idx, search_row)

    def _find_right_tab_widget(self) -> QTabWidget | None:
        for tw in self.findChildren(QTabWidget):
            for i in range(tw.count()):
                if tw.tabText(i).strip() in (
                    "Expression", "Clothing", "Characteristic",
                ):
                    return tw
        return None

    def _remove_debug_tabs(self) -> None:
        tabs = self._find_right_tab_widget()
        if tabs is None:
            return
        for tab_name in ["Quality", "Navigation", "Dependencies"]:
            for i in range(tabs.count() - 1, -1, -1):
                if tabs.tabText(i).strip() == tab_name:
                    tabs.removeTab(i)
                    break

    def _move_combos_tab_first(self) -> None:
        """Move 'Observed Combos' tab to index 0 so it's always visible on event select."""
        tabs = self._find_right_tab_widget()
        if tabs is None:
            return
        for i in range(tabs.count()):
            if "combo" in tabs.tabText(i).strip().lower():
                widget = tabs.widget(i)
                label = tabs.tabText(i)
                tabs.removeTab(i)
                tabs.insertTab(0, widget, label)
                tabs.setCurrentIndex(0)
                break

    def _simplify_combo_tab(self) -> None:
        self.combo_table.setColumnCount(2)
        self.combo_table.setHorizontalHeaderLabels(["Observed Event Combo", "Count"])

        self.combo_table.setWordWrap(True)
        self.combo_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        header = self.combo_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        self.combo_info.setVisible(False)

    def _add_right_panel(self) -> None:
        root_splitter = self.centralWidget()
        if not isinstance(root_splitter, QSplitter):
            return

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        # Image placeholder
        self.preview_image = QLabel()
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image.setMinimumSize(256, 256)
        self.preview_image.setStyleSheet(
            "background-color: #1E1E2E; border: 1px solid #333; "
            "color: #666; font-size: 13px;"
        )
        self.preview_image.setText("No Preview")
        self.preview_image.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )
        right_layout.addWidget(self.preview_image, stretch=1)

        # ── Recommended Tags panel ────────────────────────────────
        self.rec_panel = QFrame()
        self.rec_panel.setStyleSheet(
            "QFrame { background-color: #1A1A2A; border: 1px solid #333; "
            "border-radius: 4px; }"
        )
        rec_layout = QVBoxLayout(self.rec_panel)
        rec_layout.setContentsMargins(8, 6, 8, 6)
        rec_layout.setSpacing(4)

        rec_header = QLabel("Recommended Tags")
        rec_header.setStyleSheet(
            "QLabel { color: #AAB; font-size: 11px; font-weight: 600; "
            "border: none; background: transparent; }"
        )
        rec_layout.addWidget(rec_header)

        # Auto dependency label
        self._auto_dep_label = QLabel("")
        self._auto_dep_label.setStyleSheet(
            "QLabel { color: #888; font-size: 10px; font-style: italic; "
            "border: none; background: transparent; }"
        )
        self._auto_dep_label.setWordWrap(True)
        self._auto_dep_label.setVisible(False)
        rec_layout.addWidget(self._auto_dep_label)

        # Expression tags row (co-occurrence, blue)
        self._rec_expr_row = QWidget()
        self._rec_expr_row.setStyleSheet("background: transparent; border: none;")
        self._rec_expr_layout = QHBoxLayout(self._rec_expr_row)
        self._rec_expr_layout.setContentsMargins(0, 0, 0, 0)
        self._rec_expr_layout.setSpacing(4)
        expr_label = QLabel("Expression")
        expr_label.setFixedWidth(72)
        expr_label.setStyleSheet(
            "QLabel { color: #6B8FD4; font-size: 10px; border: none; "
            "background: transparent; }"
        )
        self._rec_expr_layout.addWidget(expr_label, alignment=Qt.AlignmentFlag.AlignTop)
        self._rec_expr_chip_area = QWidget()
        self._rec_expr_chip_area.setStyleSheet("background: transparent; border: none;")
        self._rec_expr_chip_layout = _FlowLayout(self._rec_expr_chip_area, spacing=3)
        self._rec_expr_chip_layout.setContentsMargins(0, 0, 0, 0)
        self._rec_expr_layout.addWidget(self._rec_expr_chip_area, stretch=1)
        rec_layout.addWidget(self._rec_expr_row)

        # Clothing tags row (co-occurrence, green)
        self._rec_cloth_row = QWidget()
        self._rec_cloth_row.setStyleSheet("background: transparent; border: none;")
        self._rec_cloth_layout = QHBoxLayout(self._rec_cloth_row)
        self._rec_cloth_layout.setContentsMargins(0, 0, 0, 0)
        self._rec_cloth_layout.setSpacing(4)
        cloth_label = QLabel("Clothing")
        cloth_label.setFixedWidth(72)
        cloth_label.setStyleSheet(
            "QLabel { color: #5DAE8B; font-size: 10px; border: none; "
            "background: transparent; }"
        )
        self._rec_cloth_layout.addWidget(cloth_label, alignment=Qt.AlignmentFlag.AlignTop)
        self._rec_cloth_chip_area = QWidget()
        self._rec_cloth_chip_area.setStyleSheet(
            "background: transparent; border: none;"
        )
        self._rec_cloth_chip_layout = _FlowLayout(self._rec_cloth_chip_area, spacing=3)
        self._rec_cloth_chip_layout.setContentsMargins(0, 0, 0, 0)
        self._rec_cloth_layout.addWidget(self._rec_cloth_chip_area, stretch=1)
        rec_layout.addWidget(self._rec_cloth_row)

        # Characteristic tags row (co-occurrence, orange)
        self._rec_char_row = QWidget()
        self._rec_char_row.setStyleSheet("background: transparent; border: none;")
        self._rec_char_layout = QHBoxLayout(self._rec_char_row)
        self._rec_char_layout.setContentsMargins(0, 0, 0, 0)
        self._rec_char_layout.setSpacing(4)
        char_label = QLabel("Characteristic")
        char_label.setFixedWidth(72)
        char_label.setStyleSheet(
            "QLabel { color: #D4A06B; font-size: 10px; border: none; "
            "background: transparent; }"
        )
        self._rec_char_layout.addWidget(char_label, alignment=Qt.AlignmentFlag.AlignTop)
        self._rec_char_chip_area = QWidget()
        self._rec_char_chip_area.setStyleSheet(
            "background: transparent; border: none;"
        )
        self._rec_char_chip_layout = _FlowLayout(self._rec_char_chip_area, spacing=3)
        self._rec_char_chip_layout.setContentsMargins(0, 0, 0, 0)
        self._rec_char_layout.addWidget(self._rec_char_chip_area, stretch=1)
        rec_layout.addWidget(self._rec_char_row)

        # Hierarchy info row
        self._rec_hier_label = QLabel("")
        self._rec_hier_label.setStyleSheet(
            "QLabel { color: #888; font-size: 10px; font-style: italic; "
            "border: none; background: transparent; }"
        )
        self._rec_hier_label.setWordWrap(True)
        rec_layout.addWidget(self._rec_hier_label)

        self.rec_panel.setVisible(False)
        right_layout.addWidget(self.rec_panel)

        # ── Prompt text area ──────────────────────────────────────
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText(
            "Select an Observed Combo to generate prompt..."
        )
        self.prompt_edit.setMaximumHeight(120)
        self.prompt_edit.setStyleSheet(
            "QTextEdit { background-color: #1E1E2E; border: 1px solid #444; "
            "color: #E0E0E0; font-size: 12px; padding: 6px; }"
        )
        right_layout.addWidget(self.prompt_edit)

        # Generate button
        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addStretch()

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setFixedWidth(80)
        self.generate_btn.setStyleSheet(
            "QPushButton { background-color: #2d6cdf; color: white; "
            "font-weight: 600; padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #3b7cf5; }"
        )
        btn_layout.addWidget(self.generate_btn)
        right_layout.addWidget(btn_row)

        root_splitter.addWidget(right_panel)
        root_splitter.setStretchFactor(0, 2)  # left / tree
        root_splitter.setStretchFactor(1, 3)  # middle / tabs
        root_splitter.setStretchFactor(2, 5)  # right / image + prompt

    # ------------------------------------------------------------------
    # Master-Detail navigation (replaces Tree/List tabs)
    # ------------------------------------------------------------------

    def _replace_tree_with_master_detail(self) -> None:
        """Replace left_tabs (Tree/List QTabWidget) with master-detail splitter."""
        # 1. Find left_tabs (the QTabWidget containing event_tree)
        left_tabs = self.event_tree.parentWidget()
        while left_tabs and not isinstance(left_tabs, QTabWidget):
            left_tabs = left_tabs.parentWidget()
        if left_tabs is None:
            return
        parent_widget = left_tabs.parentWidget()
        if parent_widget is None:
            return
        parent_layout = parent_widget.layout()
        if parent_layout is None:
            return
        tab_index = parent_layout.indexOf(left_tabs)

        # 2. Disconnect old signals, hide old tabs
        try:
            self.event_tree.itemSelectionChanged.disconnect()
        except TypeError:
            pass
        try:
            self.event_list.currentTextChanged.disconnect()
        except TypeError:
            pass
        left_tabs.setVisible(False)

        # 3. Create new widgets
        self.nav_splitter = QSplitter(Qt.Orientation.Vertical)

        # Upper: Group > Subgroup navigation tree (depth=1)
        self.subgroup_tree = QTreeWidget()
        self.subgroup_tree.setHeaderHidden(True)
        self.subgroup_tree.setIndentation(16)
        self.subgroup_tree.setAlternatingRowColors(False)
        self.subgroup_tree.setRootIsDecorated(True)
        self.subgroup_tree.itemSelectionChanged.connect(self._on_subgroup_selected)

        # Lower: Event detail tree (subcategory-grouped, collapsible)
        self.event_detail_list = QTreeWidget()
        self.event_detail_list.setHeaderHidden(True)
        self.event_detail_list.setIndentation(14)
        self.event_detail_list.setAlternatingRowColors(True)
        self.event_detail_list.setRootIsDecorated(True)
        self.event_detail_list.currentItemChanged.connect(self._on_detail_event_selected)
        self.event_detail_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.event_detail_list.customContextMenuRequested.connect(self._on_detail_context_menu)

        self.nav_splitter.addWidget(self.subgroup_tree)
        self.nav_splitter.addWidget(self.event_detail_list)
        self.nav_splitter.setStretchFactor(0, 2)
        self.nav_splitter.setStretchFactor(1, 3)

        # 4. Insert into layout
        parent_layout.insertWidget(tab_index, self.nav_splitter)

        # 5. State flags
        self._search_active = False
        self._current_nav_key: tuple[str, ...] | None = None  # (group, subgroup) or (group, subgroup, subcategory)
        self._applying_filter = False
        self._detail_event_items: dict[str, QTreeWidgetItem] = {}

        # 6. Initial population
        visible = self._get_visible_events_for_partition()
        all_events = self.events["tag_name"].astype(str).tolist()
        filtered = sorted(
            [n for n in all_events if n in visible],
            key=lambda n: (-int(self.event_post_count_rank_map.get(str(n), 0)), str(n)),
        )
        self._refresh_subgroup_navigation(filtered)
        self._select_first_subgroup()

    @staticmethod
    def _format_count(n: int) -> str:
        """763322 -> '763k', 1258076 -> '1,258k', 150 -> '150'"""
        if n >= 1000:
            return f"{n // 1000:,}k"
        return str(n)

    def _refresh_subgroup_navigation(self, filtered_events: list[str]) -> None:
        """Rebuild the upper Group > Subgroup > Subcategory navigation tree."""
        if not hasattr(self, 'subgroup_tree'):
            return

        self.subgroup_tree.blockSignals(True)
        # Remember expanded state by text prefix
        prev_expanded: set[str] = set()
        def _collect_expanded(parent, depth=0):
            count = parent.childCount() if hasattr(parent, 'childCount') else parent.topLevelItemCount()
            get = parent.child if hasattr(parent, 'child') else parent.topLevelItem
            for i in range(count):
                item = get(i)
                if item and item.isExpanded():
                    prev_expanded.add(item.text(0).split("(")[0].strip())
                if item and item.childCount() > 0:
                    _collect_expanded(item, depth + 1)
        _collect_expanded(self.subgroup_tree)
        self.subgroup_tree.clear()

        filtered_set = set(filtered_events)
        df = self.taxonomy[self.taxonomy["event_tag"].isin(filtered_set)].copy()
        if df.empty:
            self.subgroup_tree.blockSignals(False)
            return

        has_subcats = "subcategory" in df.columns
        df = df.sort_values(["group_order", "subgroup_order"] + (["subcategory_order"] if has_subcats else []))
        group_sum = df.groupby("group")["post_count"].sum().to_dict()

        for group, group_df in df.groupby("group", sort=False):
            group_label = self.group_display_map.get(group, group.title())
            group_posts = self._format_count(int(group_sum.get(group, 0)))
            group_item = QTreeWidgetItem([f"{group_label} ({group_posts})"])
            group_item.setData(0, ROLE_LEVEL, "group")
            group_item.setFlags(Qt.ItemFlag.ItemIsEnabled)

            for subgroup, sub_df in group_df.groupby("subgroup", sort=False):
                sg_label = self.subgroup_display_map.get(subgroup, subgroup)
                ev_count = len(sub_df)
                posts = self._format_count(int(sub_df["post_count"].sum()))
                sg_item = QTreeWidgetItem([f"{sg_label} ({ev_count} | {posts})"])
                sg_item.setData(0, ROLE_LEVEL, "subgroup")
                sg_item.setData(0, ROLE_EVENT, (group, subgroup))

                # Add subcategory children if more than 1 distinct subcategory
                subcats_in_sg = []
                if has_subcats:
                    non_empty = sub_df["subcategory"].astype(str).str.strip().replace("", None).replace("nan", None).dropna()
                    subcats_in_sg = non_empty.unique().tolist()

                if len(subcats_in_sg) >= 2:
                    # Subgroup becomes expandable header (still selectable to show all events)
                    for subcat, sc_df in sub_df.groupby("subcategory", sort=False):
                        subcat_str = str(subcat).strip()
                        if subcat_str in ("", "nan"):
                            continue
                        sc_label = self.subcategory_display_map.get(
                            subcat_str, subcat_str.replace("_", " ").title()
                        )
                        sc_ev_count = len(sc_df)
                        sc_posts = self._format_count(int(sc_df["post_count"].sum()))
                        sc_item = QTreeWidgetItem([f"{sc_label} ({sc_ev_count} | {sc_posts})"])
                        sc_item.setData(0, ROLE_LEVEL, "subcategory")
                        sc_item.setData(0, ROLE_EVENT, (group, subgroup, subcat_str))
                        sg_item.addChild(sc_item)

                group_item.addChild(sg_item)

            self.subgroup_tree.addTopLevelItem(group_item)
            # Restore expand state; first load -> expand all groups
            if not prev_expanded or group_label.split("(")[0].strip() in prev_expanded:
                group_item.setExpanded(True)

        # Restore subgroup expand state (only expand subgroups that were previously expanded)
        if prev_expanded:
            def _restore_expand(parent):
                count = parent.childCount() if hasattr(parent, 'childCount') else parent.topLevelItemCount()
                get = parent.child if hasattr(parent, 'child') else parent.topLevelItem
                for i in range(count):
                    item = get(i)
                    if item and item.childCount() > 0:
                        label = item.text(0).split("(")[0].strip()
                        if label in prev_expanded:
                            item.setExpanded(True)
                        _restore_expand(item)
            _restore_expand(self.subgroup_tree)

        self.subgroup_tree.blockSignals(False)

    def _make_detail_event_item(self, name: str) -> QTreeWidgetItem:
        """Create a QTreeWidgetItem for an event in the detail tree."""
        posts = self.step15_event_count_map.get(name, 0)
        item = QTreeWidgetItem([f"{name}  ({posts:,})"])
        item.setData(0, Qt.ItemDataRole.UserRole, name)
        if self.event_combo_index.get(name):
            font = QFont(item.font(0))
            font.setBold(True)
            item.setFont(0, font)
        self._detail_event_items[name] = item
        return item

    def _refresh_event_detail_list(self, event_names: list[str]) -> None:
        """Fill the event detail tree flat (no grouping) — used for search mode."""
        if not hasattr(self, 'event_detail_list'):
            return
        self.event_detail_list.blockSignals(True)
        self.event_detail_list.clear()
        self._detail_event_items = {}

        for name in event_names:
            self.event_detail_list.addTopLevelItem(self._make_detail_event_item(name))

        self.event_detail_list.setRootIsDecorated(False)
        self.event_detail_list.blockSignals(False)

    def _refresh_event_detail_list_grouped(self, group: str, subgroup: str, visible: set[str]) -> None:
        """Fill the event detail tree grouped by subcategory (collapsible sections)."""
        if not hasattr(self, 'event_detail_list'):
            return

        # Remember collapsed state
        prev_collapsed: set[str] = set()
        for i in range(self.event_detail_list.topLevelItemCount()):
            top = self.event_detail_list.topLevelItem(i)
            if top and not top.isExpanded() and top.data(0, Qt.ItemDataRole.UserRole) is None:
                prev_collapsed.add(top.text(0))

        self.event_detail_list.blockSignals(True)
        self.event_detail_list.clear()
        self._detail_event_items = {}

        df = self.taxonomy[
            (self.taxonomy["group"] == group)
            & (self.taxonomy["subgroup"] == subgroup)
            & (self.taxonomy["event_tag"].isin(visible))
        ].copy()

        if df.empty:
            self.event_detail_list.blockSignals(False)
            return

        # Determine if subcategory grouping is needed
        subcat_col = "subcategory" if "subcategory" in df.columns else None
        has_subcats = False
        if subcat_col:
            non_empty = df[subcat_col].astype(str).str.strip().replace("", None).replace("nan", None).dropna()
            has_subcats = non_empty.nunique() >= 2

        if not has_subcats:
            # No meaningful subcategories — flat list sorted by post_count
            self.event_detail_list.setRootIsDecorated(False)
            df = df.sort_values("post_count", ascending=False)
            for _, row in df.iterrows():
                self.event_detail_list.addTopLevelItem(
                    self._make_detail_event_item(str(row["event_tag"]))
                )
        else:
            # Grouped by subcategory with collapsible headers
            self.event_detail_list.setRootIsDecorated(True)
            df = df.sort_values(
                ["subcategory_order", "subcategory", "post_count", "event_tag"],
                ascending=[True, True, False, True],
            )

            current_header: QTreeWidgetItem | None = None
            prev_subcat: str | None = None

            for _, row in df.iterrows():
                name = str(row["event_tag"])
                subcat = str(row.get("subcategory", "") or "").strip()
                if subcat in ("", "nan"):
                    subcat = ""

                if subcat != prev_subcat:
                    # New subcategory header
                    if subcat:
                        label = self.subcategory_display_map.get(
                            subcat, subcat.replace("_", " ").title()
                        )
                    else:
                        label = "Other"
                    ev_count = int(len(df[df["subcategory"].astype(str).str.strip() == subcat]))
                    posts_sum = self._format_count(
                        int(df[df["subcategory"].astype(str).str.strip() == subcat]["post_count"].sum())
                    )
                    current_header = QTreeWidgetItem([f"{label} ({ev_count} | {posts_sum})"])
                    current_header.setData(0, Qt.ItemDataRole.UserRole, None)
                    current_header.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    current_header.setForeground(0, QColor("#999"))
                    self.event_detail_list.addTopLevelItem(current_header)
                    # Restore expand state; first load -> expand all
                    if not prev_collapsed or current_header.text(0) not in prev_collapsed:
                        current_header.setExpanded(True)
                    prev_subcat = subcat

                ev_item = self._make_detail_event_item(name)
                if current_header is not None:
                    current_header.addChild(ev_item)
                else:
                    self.event_detail_list.addTopLevelItem(ev_item)

        self.event_detail_list.blockSignals(False)

    def _refresh_event_detail_list_for_subcategory(
        self, group: str, subgroup: str, subcategory: str, visible: set[str]
    ) -> None:
        """Fill the event detail tree flat for a single subcategory."""
        if not hasattr(self, 'event_detail_list'):
            return
        self.event_detail_list.blockSignals(True)
        self.event_detail_list.clear()
        self._detail_event_items = {}

        df = self.taxonomy[
            (self.taxonomy["group"] == group)
            & (self.taxonomy["subgroup"] == subgroup)
            & (self.taxonomy["subcategory"].astype(str).str.strip() == subcategory)
            & (self.taxonomy["event_tag"].isin(visible))
        ].copy()

        if not df.empty:
            df = df.sort_values("post_count", ascending=False)
            for _, row in df.iterrows():
                self.event_detail_list.addTopLevelItem(
                    self._make_detail_event_item(str(row["event_tag"]))
                )

        self.event_detail_list.setRootIsDecorated(False)
        self.event_detail_list.blockSignals(False)

    def _select_first_detail_event(self) -> None:
        """Select the first selectable (non-header) event in the detail tree."""
        if not hasattr(self, 'event_detail_list'):
            return
        for i in range(self.event_detail_list.topLevelItemCount()):
            top = self.event_detail_list.topLevelItem(i)
            if not top:
                continue
            # Top-level event (flat mode)
            if top.data(0, Qt.ItemDataRole.UserRole):
                self.event_detail_list.setCurrentItem(top)
                return
            # Subcategory header — pick first child
            if top.childCount() > 0:
                top.setExpanded(True)
                self.event_detail_list.setCurrentItem(top.child(0))
                return

    def _on_subgroup_selected(self) -> None:
        """Handle subgroup or subcategory click in the upper navigation tree."""
        if not hasattr(self, 'subgroup_tree'):
            return
        item = self.subgroup_tree.currentItem()
        if item is None:
            return
        level = item.data(0, ROLE_LEVEL)
        if level not in ("subgroup", "subcategory"):
            return
        key = item.data(0, ROLE_EVENT)
        if key is None:
            return

        self._current_nav_key = key
        self._search_active = False
        visible = self._get_visible_events_for_partition()

        if level == "subcategory":
            # Show only this subcategory's events (flat)
            group, subgroup, subcategory = key
            self._refresh_event_detail_list_for_subcategory(group, subgroup, subcategory, visible)
        else:
            # Show all events in this subgroup (grouped by subcategory)
            group, subgroup = key
            self._refresh_event_detail_list_grouped(group, subgroup, visible)

        # Auto-select first event unless _apply_filter is handling selection
        if not getattr(self, '_applying_filter', False):
            self._select_first_detail_event()

    def _on_detail_event_selected(self, current, previous) -> None:
        """Handle event click in the lower detail tree."""
        if current is None:
            return
        event_name = current.data(0, Qt.ItemDataRole.UserRole)
        if not event_name:
            return
        self.current_event = event_name
        self._on_event_selected(event_name)

    def _on_detail_context_menu(self, pos) -> None:
        """Right-click context menu on event detail tree (staging)."""
        if not hasattr(self, 'event_detail_list'):
            return
        item = self.event_detail_list.itemAt(pos)
        if item is None:
            return
        event_name = item.data(0, Qt.ItemDataRole.UserRole)
        if not event_name:
            return

        menu = QMenu(self)
        if event_name in self.staged_events:
            action = menu.addAction(f"Unstage: {event_name}")
            action.triggered.connect(lambda _checked=False, ev=event_name: self._unstage_event(ev))
        else:
            if len(self.staged_events) < MAX_STAGED:
                action = menu.addAction(f"Stage for Combo: {event_name}")
                action.triggered.connect(lambda _checked=False, ev=event_name: self._stage_event(ev))
            else:
                action = menu.addAction(f"Stage limit reached ({MAX_STAGED})")
                action.setEnabled(False)
        if self.staged_events:
            menu.addSeparator()
            clear_action = menu.addAction(f"Clear all staged ({len(self.staged_events)})")
            clear_action.triggered.connect(self._clear_staging)
        menu.exec(self.event_detail_list.viewport().mapToGlobal(pos))

    def _select_detail_event(self, event_name: str) -> None:
        """Programmatically select an event in the detail tree."""
        item = self._detail_event_items.get(event_name)
        if item is not None:
            # Ensure parent is expanded so item is visible
            parent = item.parent()
            if parent is not None:
                parent.setExpanded(True)
            self.event_detail_list.setCurrentItem(item)

    def _select_first_subgroup(self) -> None:
        """Select the first leaf (subcategory if present, else subgroup) in the navigation tree."""
        if not hasattr(self, 'subgroup_tree'):
            return
        for gi in range(self.subgroup_tree.topLevelItemCount()):
            group_item = self.subgroup_tree.topLevelItem(gi)
            if group_item and group_item.childCount() > 0:
                first_sub = group_item.child(0)
                if first_sub:
                    # If subgroup has subcategory children, pick first subcategory
                    if first_sub.childCount() > 0:
                        first_sub.setExpanded(True)
                        self.subgroup_tree.setCurrentItem(first_sub.child(0))
                    else:
                        self.subgroup_tree.setCurrentItem(first_sub)
                    return

    def _restore_subgroup_selection(self, key: tuple[str, ...]) -> None:
        """Restore navigation selection by key: (group, subgroup) or (group, subgroup, subcategory)."""
        if not hasattr(self, 'subgroup_tree'):
            return
        for gi in range(self.subgroup_tree.topLevelItemCount()):
            group_item = self.subgroup_tree.topLevelItem(gi)
            if group_item is None:
                continue
            for si in range(group_item.childCount()):
                sub_item = group_item.child(si)
                if sub_item is None:
                    continue
                if sub_item.data(0, ROLE_EVENT) == key:
                    self.subgroup_tree.setCurrentItem(sub_item)
                    return
                # Search subcategory children
                if len(key) == 3:
                    for ci in range(sub_item.childCount()):
                        sc_item = sub_item.child(ci)
                        if sc_item and sc_item.data(0, ROLE_EVENT) == key:
                            sub_item.setExpanded(True)
                            self.subgroup_tree.setCurrentItem(sc_item)
                            return
        # Key not found — fallback to first subgroup
        self._select_first_subgroup()

    # ------------------------------------------------------------------
    # Recommended tags
    # ------------------------------------------------------------------

    def _collect_auto_deps(self, event_names: list[str]) -> list[str]:
        """Collect dependency tags from recommendations JSON that auto-insert into prompt."""
        event_set = set(event_names)
        seen: set[str] = set()
        deps: list[str] = []
        for ev in event_names:
            rec = self._recommendations.get(ev)
            if rec is None:
                continue
            for tag_list_key in ("object_tags", "clothing_tags"):
                for t in rec.get(tag_list_key, []):
                    tag = t["tag"]
                    if tag not in seen and tag not in event_set:
                        seen.add(tag)
                        deps.append(tag)
        return deps

    def _get_hierarchy_info(
        self, event_names: list[str],
    ) -> tuple[str | None, str | None]:
        """Extract hierarchy parent/root from recommendations JSON."""
        hier_parent: str | None = None
        hier_root: str | None = None
        for ev in event_names:
            rec = self._recommendations.get(ev)
            if rec is None:
                continue
            if hier_parent is None and rec.get("hierarchy_parent"):
                hier_parent = rec["hierarchy_parent"]
            if hier_root is None and rec.get("hierarchy_root"):
                hier_root = rec["hierarchy_root"]
        return hier_parent, hier_root

    def _query_cooccurrence_for_event(self, event_name: str) -> dict[str, list[tuple[str, float]]]:
        """Query co-occurrence data for a single event (partition-stable, no dep filtering).

        Returns {category: [(tag, confidence), ...]} cached per partition lifetime.
        """
        if event_name in self._cooc_cache:
            return self._cooc_cache[event_name]

        result: dict[str, list[tuple[str, float]]] = {"expr": [], "cloth": [], "char": []}

        if self.step15_active_data is None:
            self._cooc_cache[event_name] = result
            return result

        # Expression
        expr_df = self.step15_active_data["expr"]
        expr_sub = expr_df[expr_df["event_tag"] == event_name].copy()
        if not expr_sub.empty:
            expr_sub = expr_sub[expr_sub["confidence"] >= COOC_EXPR_CONFIDENCE_MIN]
            expr_sub = expr_sub.sort_values("confidence", ascending=False).head(COOC_TOP_N_PER_EVENT)
            for _, row in expr_sub.iterrows():
                result["expr"].append((str(row["expression_tag"]), float(row["confidence"])))

        # Clothing
        cloth_df = self.step15_active_data["cloth"]
        cloth_sub = cloth_df[cloth_df["event_tag"] == event_name].copy()
        if not cloth_sub.empty:
            cloth_sub = self._hide_color_prefixed_rows(cloth_sub, "clothing_tag")
            cloth_sub = cloth_sub[cloth_sub["confidence"] >= COOC_CLOTH_CONFIDENCE_MIN]
            cloth_sub = cloth_sub.sort_values("confidence", ascending=False).head(COOC_TOP_N_PER_EVENT)
            for _, row in cloth_sub.iterrows():
                result["cloth"].append((str(row["clothing_tag"]), float(row["confidence"])))

        # Characteristic
        char_df = self.step15_active_data["char"]
        char_sub = char_df[char_df["event_tag"] == event_name].copy()
        if not char_sub.empty:
            char_sub = self._hide_color_prefixed_rows(char_sub, "characteristic_tag")
            char_sub = char_sub[char_sub["confidence"] >= COOC_CHAR_CONFIDENCE_MIN]
            char_sub = char_sub.sort_values("confidence", ascending=False).head(COOC_TOP_N_PER_EVENT)
            for _, row in char_sub.iterrows():
                result["char"].append((str(row["characteristic_tag"]), float(row["confidence"])))

        self._cooc_cache[event_name] = result
        return result

    def _merge_cooccurrence_for_events(
        self, event_names: list[str],
        affinity_events: set[str] | None = None,
    ) -> dict[str, list[tuple[str, float]]]:
        """Merge co-occurrence across multiple events. Union with max confidence, top N.

        Excludes auto-dependency tags at merge time (not cached).
        When *affinity_events* is provided, only events in that set are queried
        (intersection with event_names; falls back to full list if empty).
        """
        if affinity_events is not None:
            filtered = [ev for ev in event_names if ev in affinity_events]
            query_events = filtered if filtered else event_names
        else:
            query_events = event_names

        auto_dep_set = set(self._auto_dep_tags)
        merged: dict[str, dict[str, float]] = {"expr": {}, "cloth": {}, "char": {}}

        for ev in query_events:
            per_event = self._query_cooccurrence_for_event(ev)
            for cat in ("expr", "cloth", "char"):
                for tag, conf in per_event[cat]:
                    if tag in auto_dep_set:
                        continue
                    if tag not in merged[cat] or conf > merged[cat][tag]:
                        merged[cat][tag] = conf

        result: dict[str, list[tuple[str, float]]] = {}
        for cat in ("expr", "cloth", "char"):
            sorted_tags = sorted(merged[cat].items(), key=lambda x: -x[1])
            result[cat] = sorted_tags[:COOC_TOP_N_MERGED]
        return result

    def _clear_chip_layout(self, layout: QLayout) -> None:
        while layout.count() > 0:
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _make_tag_chip(
        self, tag: str, category: str, confidence: float = 0.0,
    ) -> QPushButton:
        chip = QPushButton(tag)
        chip.setCheckable(True)
        chip.setChecked(self._active_rec_tags.get(tag, False))
        chip.setProperty("rec_tag", tag)

        if confidence > 0:
            chip.setToolTip(f"{tag} (confidence: {confidence:.3f})")

        if category == "expression":
            on_bg, on_border = "#2A3A5C", "#4A7AD4"
            off_bg, off_border = "#1E1E2E", "#444"
        elif category == "clothing":
            on_bg, on_border = "#1E3A2E", "#3DAE7B"
            off_bg, off_border = "#1E1E2E", "#444"
        else:  # characteristic
            on_bg, on_border = "#3A2E1E", "#D4A06B"
            off_bg, off_border = "#1E1E2E", "#444"

        chip.setStyleSheet(f"""
            QPushButton {{
                font-size: 11px; padding: 2px 7px; border-radius: 3px;
                color: #CCC; background: {on_bg}; border: 1px solid {on_border};
            }}
            QPushButton:!checked {{
                color: #777; background: {off_bg}; border: 1px solid {off_border};
            }}
            QPushButton:hover {{ color: #FFF; }}
        """)

        chip.toggled.connect(lambda checked, t=tag: self._on_chip_toggled(t, checked))
        return chip

    def _on_chip_toggled(self, tag: str, checked: bool) -> None:
        self._active_rec_tags[tag] = checked
        if self._refreshing_chips:
            return
        event_names = self._get_current_event_names()
        if event_names:
            self._refresh_rec_chips(event_names)
        self._rebuild_prompt()

    def _get_current_event_names(self) -> list[str]:
        """Extract current event names from combo_table selection or current_event."""
        clean_events: list[str] = []
        row = self.combo_table.currentRow()
        if row >= 0:
            item = self.combo_table.item(row, 0)
            if item is not None:
                combo_text = item.text()
                for ev in (t.strip() for t in combo_text.split(",") if t.strip()):
                    if ev.startswith("[") and ev.endswith("]"):
                        clean_events.append(ev[1:-1])
                    else:
                        clean_events.append(ev)
        if not clean_events and self.current_event:
            clean_events = [self.current_event]
        return clean_events

    def _get_affinity_events(self, selected_tags: list[str]) -> set[str] | None:
        """Reverse-lookup: find events where all selected tags have high co-occurrence."""
        if not selected_tags or self.step15_active_data is None:
            return None
        cat_map = [
            ("expression_tag", "expr"),
            ("clothing_tag", "cloth"),
            ("characteristic_tag", "char"),
        ]
        affinity: set[str] | None = None
        for tag in selected_tags:
            tag_events: set[str] = set()
            for tag_col, df_key in cat_map:
                df = self.step15_active_data[df_key]
                sub = df[(df[tag_col] == tag) & (df["confidence"] >= COOC_AFFINITY_THRESHOLD)]
                tag_events.update(sub["event_tag"].tolist())
            affinity = tag_events if affinity is None else (affinity & tag_events)
        return affinity if affinity else None

    def _update_recommendations(self, event_names: list[str]) -> None:
        # 1. Auto dependency tags
        self._auto_dep_tags = self._collect_auto_deps(event_names)
        if self._auto_dep_tags:
            self._auto_dep_label.setText("Auto: " + ", ".join(self._auto_dep_tags))
            self._auto_dep_label.setVisible(True)
        else:
            self._auto_dep_label.setVisible(False)

        # 2. Refresh co-occurrence chips (resets toggle state for new combo)
        self._active_rec_tags = {}
        self._refresh_rec_chips(event_names)

        # 3. Hierarchy info from JSON
        hier_parent, _hier_root = self._get_hierarchy_info(event_names)
        if hier_parent:
            primary = event_names[0] if event_names else ""
            self._rec_hier_label.setText(f"{primary} \u2192 {hier_parent}")
            self._rec_hier_label.setVisible(True)
        else:
            self._rec_hier_label.setVisible(False)

    def _refresh_rec_chips(self, event_names: list[str]) -> None:
        """Rebuild co-occurrence chip panels using affinity filtering from selected tags."""
        self._refreshing_chips = True
        try:
            selected_tags = self._get_active_rec_tags()
            affinity = self._get_affinity_events(selected_tags)

            cooc = self._merge_cooccurrence_for_events(event_names, affinity_events=affinity)
            expr_tags = cooc.get("expr", [])
            cloth_tags = cooc.get("cloth", [])
            char_tags = cooc.get("char", [])

            has_any = bool(
                self._auto_dep_tags or expr_tags or cloth_tags or char_tags
                or self._rec_hier_label.isVisible()
            )
            self.rec_panel.setVisible(has_any)
            if not has_any:
                self._active_rec_tags = {}
                return

            # Preserve existing ON state; add new tags as OFF
            new_active: dict[str, bool] = {}
            for tag, _conf in expr_tags + cloth_tags + char_tags:
                new_active[tag] = self._active_rec_tags.get(tag, False)
            self._active_rec_tags = new_active

            # Populate expression chips
            self._clear_chip_layout(self._rec_expr_chip_layout)
            if expr_tags:
                for tag, conf in expr_tags:
                    self._rec_expr_chip_layout.addWidget(
                        self._make_tag_chip(tag, "expression", conf)
                    )
                self._rec_expr_row.setVisible(True)
            else:
                self._rec_expr_row.setVisible(False)

            # Populate clothing chips
            self._clear_chip_layout(self._rec_cloth_chip_layout)
            if cloth_tags:
                for tag, conf in cloth_tags:
                    self._rec_cloth_chip_layout.addWidget(
                        self._make_tag_chip(tag, "clothing", conf)
                    )
                self._rec_cloth_row.setVisible(True)
            else:
                self._rec_cloth_row.setVisible(False)

            # Populate characteristic chips
            self._clear_chip_layout(self._rec_char_chip_layout)
            if char_tags:
                for tag, conf in char_tags:
                    self._rec_char_chip_layout.addWidget(
                        self._make_tag_chip(tag, "characteristic", conf)
                    )
                self._rec_char_row.setVisible(True)
            else:
                self._rec_char_row.setVisible(False)
        finally:
            self._refreshing_chips = False

    def _get_active_rec_tags(self) -> list[str]:
        return [tag for tag, on in self._active_rec_tags.items() if on]

    def _rebuild_prompt(self) -> None:
        """Rebuild prompt text from current state (combo events + active recs)."""
        person_category = str(self.character_combo.currentData() or "")
        person_tags = _PERSON_TAG_MAP.get(person_category, [])
        rating_tag = _RATING_TAG_MAP.get(self.current_rating, "")

        clean_events = self._get_current_event_names()
        if not clean_events:
            return

        active_recs = self._get_active_rec_tags()
        # Avoid duplicates: don't add tags already present in events
        event_set = set(clean_events)
        unique_deps = [t for t in self._auto_dep_tags if t not in event_set]
        all_used = event_set | set(unique_deps)
        unique_recs = [t for t in active_recs if t not in all_used]

        parts = (
            list(person_tags)
            + ([rating_tag] if rating_tag else [])
            + clean_events
            + unique_deps
            + unique_recs
        )
        self.prompt_edit.setPlainText(", ".join(parts))

    def _on_combo_selected(self) -> None:
        row = self.combo_table.currentRow()
        if row < 0:
            return
        item = self.combo_table.item(row, 0)
        if item is None:
            return
        combo_text = item.text()

        # Parse events from combo
        raw_events = [t.strip() for t in combo_text.split(",") if t.strip()]
        clean_events: list[str] = []
        for ev in raw_events:
            if ev.startswith("[") and ev.endswith("]"):
                clean_events.append(ev[1:-1])
            else:
                clean_events.append(ev)

        # Update recommendation panel (this resets chip states)
        self._update_recommendations(clean_events)

        # Build prompt
        self._rebuild_prompt()

    # ------------------------------------------------------------------
    # Staging UI & context menu
    # ------------------------------------------------------------------

    def _setup_staging_ui(self) -> None:
        # Insert a staging indicator bar between reason_label and the tabs
        parent_layout = self.reason_label.parentWidget().layout()

        self.staging_bar = QWidget()
        staging_layout = QHBoxLayout(self.staging_bar)
        staging_layout.setContentsMargins(0, 2, 0, 2)
        staging_layout.setSpacing(8)

        self.staging_label = QLabel("Staged: (none)")
        self.staging_label.setWordWrap(True)
        self.staging_label.setStyleSheet("color: #666; font-size: 12px;")

        self.staging_clear_btn = QPushButton("Clear")
        self.staging_clear_btn.setFixedWidth(60)
        self.staging_clear_btn.clicked.connect(self._clear_staging)
        self.staging_clear_btn.setVisible(False)

        staging_layout.addWidget(self.staging_label)
        staging_layout.addWidget(self.staging_clear_btn)
        staging_layout.addStretch()

        # reason_label is at index 1 in the right panel layout → insert after it
        parent_layout.insertWidget(2, self.staging_bar)

        # Switch-to partition bar (below staging bar)
        self.switch_to_bar = QWidget()
        switch_layout = QHBoxLayout(self.switch_to_bar)
        switch_layout.setContentsMargins(0, 0, 0, 2)
        switch_layout.setSpacing(6)

        self.switch_label = QLabel("Switch to")
        self.switch_label.setFixedWidth(55)
        self.switch_label.setStyleSheet("color: #888; font-size: 11px;")
        switch_layout.addWidget(self.switch_label)

        self.switch_partition_combo = QComboBox()
        self.switch_partition_combo.setMaxVisibleItems(20)
        self.switch_partition_combo.setItemDelegate(
            _RichComboDelegate(self.switch_partition_combo)
        )
        self.switch_partition_combo.setStyleSheet(
            "QComboBox { font-size: 11px; padding: 2px 4px; }"
        )
        self.switch_partition_combo.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        )
        self.switch_partition_combo.currentIndexChanged.connect(
            self._on_switch_partition_selected
        )
        switch_layout.addWidget(self.switch_partition_combo)

        self.switch_to_bar.setVisible(False)
        parent_layout.insertWidget(3, self.switch_to_bar)

        # Enable context menu on tree
        self.event_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.event_tree.customContextMenuRequested.connect(self._on_tree_context_menu)

    def _on_tree_context_menu(self, pos) -> None:
        item = self.event_tree.itemAt(pos)
        if item is None:
            return
        if item.data(0, ROLE_LEVEL) != "event":
            return
        event_name = str(item.data(0, ROLE_EVENT) or "")
        if not event_name:
            return

        menu = QMenu(self)
        if event_name in self.staged_events:
            action = menu.addAction(f"Unstage: {event_name}")
            action.triggered.connect(lambda _checked=False, ev=event_name: self._unstage_event(ev))
        else:
            if len(self.staged_events) < MAX_STAGED:
                action = menu.addAction(f"Stage for Combo: {event_name}")
                action.triggered.connect(lambda _checked=False, ev=event_name: self._stage_event(ev))
            else:
                action = menu.addAction(f"Stage limit reached ({MAX_STAGED})")
                action.setEnabled(False)
        if self.staged_events:
            menu.addSeparator()
            clear_action = menu.addAction(f"Clear all staged ({len(self.staged_events)})")
            clear_action.triggered.connect(self._clear_staging)
        menu.exec(self.event_tree.viewport().mapToGlobal(pos))

    def _stage_event(self, event_name: str) -> None:
        if event_name in self.staged_events:
            return
        if len(self.staged_events) >= MAX_STAGED:
            return
        self.staged_events.append(event_name)
        self._event_pair_cache = None
        if self.step15_active_data is not None:
            combo_df = self.step15_active_data["combo"]
            sub = combo_df[combo_df["event_tag"] == event_name].sort_values(
                "count", ascending=False
            ).head(STAGED_COMBO_TOP_N)
            combos: list[tuple[frozenset[str], int]] = []
            for _, row in sub.iterrows():
                combo_text = str(row["observed_event_combo"])
                combo_set = frozenset(t.strip() for t in combo_text.split(",") if t.strip())
                combos.append((combo_set, int(row["count"])))
            self.staged_combos_map[event_name] = combos
        self._update_staging_display()
        if self.current_event:
            self._fill_observed_combos(self.current_event)

    def _unstage_event(self, event_name: str) -> None:
        if event_name in self.staged_events:
            self.staged_events.remove(event_name)
            self.staged_combos_map.pop(event_name, None)
            self._event_pair_cache = None
            self._update_staging_display()
            if self.current_event:
                self._fill_observed_combos(self.current_event)

    def _clear_staging(self) -> None:
        self.staged_events = []
        self.staged_combos_map = {}
        self._event_pair_cache = None
        self._update_staging_display()
        if self.current_event:
            self._fill_observed_combos(self.current_event)

    def _check_staging_deadlock(self) -> list[tuple[str, str]]:
        """Return list of incompatible event pairs among staged events."""
        if len(self.staged_events) < 2:
            return []
        pair_index = self._get_event_pair_index()
        bad_pairs: list[tuple[str, str]] = []
        for i in range(len(self.staged_events)):
            for j in range(i + 1, len(self.staged_events)):
                if frozenset({self.staged_events[i], self.staged_events[j]}) not in pair_index:
                    bad_pairs.append((self.staged_events[i], self.staged_events[j]))
        return bad_pairs

    def _update_staging_display(self) -> None:
        if self.staged_events:
            parts = []
            for ev in self.staged_events:
                pc = self.step15_event_count_map.get(ev, 0)
                cn = len(self.staged_combos_map.get(ev, []))
                parts.append(f"{ev} ({pc:,}p, {cn}c)")

            deadlock_pairs = self._check_staging_deadlock()
            if deadlock_pairs:
                conflict_desc = "; ".join(f"{a} x {b}" for a, b in deadlock_pairs)
                self.staging_label.setText(
                    f"DEADLOCK ({len(self.staged_events)}/{MAX_STAGED}): "
                    + " + ".join(parts)
                    + f"  [{conflict_desc}]"
                )
                self.staging_label.setStyleSheet(
                    "color: #E04040; font-size: 12px; font-weight: 600;"
                )
                nav_widget = self.nav_splitter if hasattr(self, 'nav_splitter') else self.event_tree
                nav_widget.setEnabled(False)
            else:
                self.staging_label.setText(
                    f"Staged ({len(self.staged_events)}/{MAX_STAGED}): " + " + ".join(parts)
                )
                self.staging_label.setStyleSheet(
                    "color: #E8A838; font-size: 12px; font-weight: 600;"
                )
                nav_widget = self.nav_splitter if hasattr(self, 'nav_splitter') else self.event_tree
                nav_widget.setEnabled(True)
            self.staging_clear_btn.setVisible(True)
        else:
            self.staging_label.setText("Staged: (none)")
            self.staging_label.setStyleSheet("color: #666; font-size: 12px;")
            self.staging_clear_btn.setVisible(False)
            nav_widget = self.nav_splitter if hasattr(self, 'nav_splitter') else self.event_tree
            nav_widget.setEnabled(True)

    # ------------------------------------------------------------------

    def _on_character_changed_step15(self, _index: int) -> None:
        if getattr(self, '_switching_partition', False):
            return
        self._refresh_step15_partition_binding()

    def _on_rating_toggled(self, button, checked: bool) -> None:  # type: ignore[override]
        super()._on_rating_toggled(button, checked)
        if not self._step15_ready or getattr(self, '_switching_partition', False):
            return
        self._refresh_step15_partition_binding()

    def _on_event_selected(self, event_name: str) -> None:  # type: ignore[override]
        super()._on_event_selected(event_name)
        # Strip "Event: " prefix from title label
        txt = self.title_label.text()
        if txt.startswith("Event: "):
            self.title_label.setText(txt[7:])
        if not self._step15_ready:
            return
        self._update_recommendations([event_name])
        self._update_switch_to_combo(event_name)

    # ------------------------------------------------------------------
    # Switch-to partition combo
    # ------------------------------------------------------------------

    def _update_switch_to_combo(self, event_name: str) -> None:
        """Populate the switch-to combo with partitions where this event appears."""
        if not hasattr(self, 'switch_partition_combo'):
            return

        entries = self._event_partition_index.get(event_name)
        if not entries:
            self.switch_to_bar.setVisible(False)
            return

        current_partition = self._get_selected_partition_name()

        self.switch_partition_combo.blockSignals(True)
        self.switch_partition_combo.clear()
        current_idx = 0
        for i, (partition_name, post_count) in enumerate(entries):
            try:
                rating_prefix, person_key = _parse_partition_name(partition_name)
            except (ValueError, IndexError):
                continue
            rating_short = _RATING_SHORT.get(rating_prefix, rating_prefix.upper())
            person_label = PERSON_PARTITION_LABELS.get(
                person_key, person_key.replace("_", " ")
            )
            count_str = _format_count(post_count)
            display = f"[{rating_short}] {person_label} ({count_str})"
            self.switch_partition_combo.addItem(display, userData=partition_name)
            item_idx = self.switch_partition_combo.count() - 1
            html = _format_switch_item_html(rating_short, person_label, count_str)
            self.switch_partition_combo.setItemData(item_idx, html, _ROLE_HTML)
            if partition_name == current_partition:
                current_idx = i

        self.switch_partition_combo.setCurrentIndex(current_idx)
        self.switch_partition_combo.blockSignals(False)
        self.switch_to_bar.setVisible(True)

    def _on_switch_partition_selected(self, index: int) -> None:
        """Handle user selecting a different partition from the switch-to combo."""
        if index < 0 or not hasattr(self, 'switch_partition_combo'):
            return
        partition_name = self.switch_partition_combo.itemData(index)
        if not partition_name:
            return

        current_partition = self._get_selected_partition_name()
        if partition_name == current_partition:
            return

        # Parse target rating and person category
        try:
            rating_prefix, person_key = _parse_partition_name(partition_name)
        except (ValueError, IndexError):
            return
        target_rating = _PREFIX_TO_RATING.get(rating_prefix)
        if not target_rating:
            return

        # Remember current event for re-selection after partition switch
        prev_event = self.current_event

        self._switching_partition = True
        try:
            # Set rating button
            btn = self.rating_buttons.get(target_rating)
            if btn and not btn.isChecked():
                btn.setChecked(True)

            # Set character combo
            for i in range(self.character_combo.count()):
                if self.character_combo.itemData(i) == person_key:
                    self.character_combo.setCurrentIndex(i)
                    break
        finally:
            self._switching_partition = False

        # Single refresh
        self._refresh_step15_partition_binding()

        # Re-select previous event if it exists in the new partition
        if prev_event:
            self._reselect_event_after_switch(prev_event)

    def _reselect_event_after_switch(self, event_name: str) -> None:
        """Re-select an event after partition switch, navigating subgroup tree."""
        if not hasattr(self, 'subgroup_tree'):
            return

        # Check if event exists in new partition
        if event_name not in self.step15_event_count_map:
            return

        # Find group/subgroup for event in taxonomy
        match = self.taxonomy[self.taxonomy["event_tag"] == event_name]
        if match.empty:
            return
        row = match.iloc[0]
        group = str(row["group"])
        subgroup = str(row["subgroup"])

        # Navigate to the subgroup in the tree
        key: tuple[str, ...] = (group, subgroup)
        self._restore_subgroup_selection(key)

        # Select the event in the detail tree
        self._select_detail_event(event_name)

    def _get_selected_partition_name(self) -> str:
        rating_prefix = RATING_PREFIX_MAP.get(self.current_rating, "")
        person_partition = str(self.character_combo.currentData() or "")
        if not rating_prefix or not person_partition:
            return ""
        return f"{rating_prefix}_{person_partition}"

    def _refresh_step15_partition_binding(self) -> None:
        self.step15_available_partitions = _discover_step15_partitions()
        self._event_pair_cache = None
        self._cooc_cache = {}
        partition_name = self._get_selected_partition_name()
        self.step15_active_partition_name = partition_name

        if not partition_name:
            self.step15_active_data = None
            self.step15_event_count_map = {}
            self._apply_partition_tree_projection()
            self._apply_partition_status()
            return

        if partition_name not in self.step15_available_partitions:
            self.step15_active_data = None
            self.step15_event_count_map = {}
            self._apply_partition_tree_projection()
            self._apply_partition_status()
            if self.current_event:
                self._clear_partition_bound_tables()
            return

        try:
            data = self._load_step15_partition_data(partition_name)
        except Exception as exc:
            self.step15_active_data = None
            self.step15_event_count_map = {}
            self._apply_partition_tree_projection()
            self.reason_label.setText(f"근거: step15 load failed ({partition_name}) - {exc}")
            if self.current_event:
                self._clear_partition_bound_tables()
            return
        self.step15_active_data = data
        event_catalog = data.get("event_catalog")
        if isinstance(event_catalog, pd.DataFrame) and len(event_catalog) > 0:
            self.step15_event_count_map = {
                str(r.event_tag): int(r.post_count)
                for r in event_catalog[["event_tag", "post_count"]].itertuples(index=False)
            }
        else:
            self.step15_event_count_map = {}
        self._apply_partition_tree_projection()
        self._apply_partition_status()
        if self.current_event:
            self._on_event_selected(self.current_event)

    def _apply_partition_status(self) -> None:
        name = self.step15_active_partition_name or "-"
        if self.step15_active_data is None:
            self.reason_label.setText(f"근거: step15 partition 미생성 또는 미선택 ({name})")
            self._render_quality()
            return

        quality = self.step15_active_data.get("quality", {})
        rows = int(quality.get("rows_total", 0))
        retained = quality.get("observed_combo", {}).get("retained_threshold", 0.9)
        self.reason_label.setText(
            f"근거: step15 partition={name} | rows={rows:,} | retained_conf>{retained}"
        )
        self._render_quality()

    def _load_step15_partition_data(self, partition_name: str) -> dict[str, Any]:
        cached = self.step15_cache.get(partition_name)
        if cached is not None:
            return cached

        zf = open_data_zip()
        _zp = _zread_parquet
        _zj = _zread_json
        _ze = _zexists

        prefix = f"partitions/{partition_name}"
        required = {
            "combo": f"{prefix}/event_observed_combo.parquet",
            "expr": f"{prefix}/event_expression_cooccurrence.parquet",
            "cloth": f"{prefix}/event_clothing_cooccurrence.parquet",
            "char": f"{prefix}/event_characteristic_cooccurrence.parquet",
            "quality": f"{prefix}/quality_metrics_step15.json",
        }
        missing = [k for k, arc in required.items() if not _ze(zf, arc)]
        if missing:
            raise FileNotFoundError(f"{partition_name}: missing files {', '.join(missing)}")

        catalog_arc = f"{prefix}/event_catalog.parquet"
        payload: dict[str, Any] = {
            "combo": _zp(zf, required["combo"]),
            "expr": _zp(zf, required["expr"]),
            "cloth": _zp(zf, required["cloth"]),
            "char": _zp(zf, required["char"]),
            "event_catalog": _zp(zf, catalog_arc)
            if _ze(zf, catalog_arc)
            else pd.DataFrame(columns=["event_tag", "post_count"]),
            "quality": _zj(zf, required["quality"]),
        }
        self.step15_cache[partition_name] = payload
        return payload

    def _apply_partition_tree_projection(self) -> None:
        # Keep base group/subgroup taxonomy from lightweight baseline, but project
        # partition-specific usage counts into the tree/list ranking.
        if self.step15_active_data is None:
            self.taxonomy = self._base_taxonomy.copy()
            self.event_post_count_rank_map = dict(self._base_event_post_count_rank_map)
            self._apply_filter(self.search_input.text())
            return

        tx = self._base_taxonomy.copy()
        tx["post_count"] = tx["event_tag"].map(lambda t: int(self.step15_event_count_map.get(str(t), 0)))

        # Re-rank group/subgroup/subcategory by partition-specific post volume.
        if len(tx) > 0:
            group_sum = tx.groupby("group")["post_count"].sum().sort_values(ascending=False)
            group_rank = {g: i for i, g in enumerate(group_sum.index.tolist())}
            tx["group_order"] = tx["group"].map(lambda g: int(group_rank.get(g, 999))).astype(int)

            subgroup_sum = (
                tx.groupby(["group", "subgroup"])["post_count"].sum().sort_values(ascending=False)
            )
            subgroup_rank: dict[tuple[str, str], int] = {}
            seen_by_group: dict[str, int] = {}
            for group, subgroup in subgroup_sum.index.tolist():
                cur = seen_by_group.get(group, 0)
                subgroup_rank[(group, subgroup)] = cur
                seen_by_group[group] = cur + 1
            tx["subgroup_order"] = tx.apply(
                lambda r: int(subgroup_rank.get((str(r["group"]), str(r["subgroup"])), 999)),
                axis=1,
            )

            if "subcategory" in tx.columns:
                subcat_sum = (
                    tx.groupby(["group", "subgroup", "subcategory"])["post_count"]
                    .sum()
                    .sort_values(ascending=False)
                )
                subcat_rank: dict[tuple[str, str, str], int] = {}
                seen_by_bucket: dict[tuple[str, str], int] = {}
                for group, subgroup, subcat in subcat_sum.index.tolist():
                    bucket = (group, subgroup)
                    cur = seen_by_bucket.get(bucket, 0)
                    subcat_rank[(group, subgroup, subcat)] = cur
                    seen_by_bucket[bucket] = cur + 1
                tx["subcategory_order"] = tx.apply(
                    lambda r: int(
                        subcat_rank.get(
                            (str(r["group"]), str(r["subgroup"]), str(r.get("subcategory", ""))),
                            999,
                        )
                    ),
                    axis=1,
                )

        self.taxonomy = tx
        self.event_post_count_rank_map = {
            event: int(self.step15_event_count_map.get(str(event), 0))
            for event in self.events["tag_name"].astype(str).tolist()
        }
        self._apply_filter(self.search_input.text())

    def _get_visible_events_for_partition(self) -> set[str]:
        if self.step15_active_data is None:
            return set(self.events["tag_name"].astype(str).tolist())
        return {k for k, v in self.step15_event_count_map.items() if int(v) > 0}

    def _refresh_event_list(self, filtered_events: list[str]) -> None:  # type: ignore[override]
        if hasattr(self, 'nav_splitter'):
            return  # No-op: master-detail handles navigation
        super()._refresh_event_list(filtered_events)

    def _refresh_event_tree(self, filtered_events: list[str]) -> None:  # type: ignore[override]
        """Simplified 3-level tree: Group -> Subgroup -> Event (no subcategory)."""
        if hasattr(self, 'nav_splitter'):
            return  # No-op: master-detail handles navigation
        self.tree_event_items = {}
        filtered_set = set(filtered_events)

        df = self.taxonomy[self.taxonomy["event_tag"].isin(filtered_set)].copy()
        if len(df) == 0:
            self.event_tree.blockSignals(True)
            self.event_tree.clear()
            self.event_tree.blockSignals(False)
            return

        df = df.sort_values(
            ["group_order", "group", "subgroup_order", "subgroup", "post_count", "event_tag"],
            ascending=[True, True, True, True, False, True],
        )

        has_step15 = self.step15_active_data is not None
        group_sum_map = df.groupby("group")["post_count"].sum().to_dict()
        subgroup_sum_map = df.groupby(["group", "subgroup"])["post_count"].sum().to_dict()

        self.event_tree.blockSignals(True)
        self.event_tree.clear()

        for group_name, group_df in df.groupby("group", sort=False):
            group_item = QTreeWidgetItem()
            group_label = self.group_display_map.get(group_name, group_name.title())
            group_event_count = int(len(group_df))
            group_posts = int(group_sum_map.get(group_name, 0))
            if has_step15:
                group_item.setText(0, f"{group_label} ({group_event_count:,} | {group_posts:,} posts)")
            else:
                group_item.setText(0, f"{group_label} ({group_event_count:,})")
            group_item.setText(1, f"{group_event_count:,}")
            group_item.setTextAlignment(1, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
            group_item.setData(0, ROLE_LEVEL, "group")
            self.event_tree.addTopLevelItem(group_item)

            for subgroup_name, subgroup_df in group_df.groupby("subgroup", sort=False):
                subgroup_item = QTreeWidgetItem()
                subgroup_label = self.subgroup_display_map.get(subgroup_name, subgroup_name)
                subgroup_event_count = int(len(subgroup_df))
                subgroup_posts = int(subgroup_sum_map.get((group_name, subgroup_name), 0))
                if has_step15:
                    subgroup_item.setText(0, f"{subgroup_label} ({subgroup_event_count:,} | {subgroup_posts:,} posts)")
                else:
                    subgroup_item.setText(0, f"{subgroup_label} ({subgroup_event_count:,})")
                subgroup_item.setText(1, f"{subgroup_event_count:,}")
                subgroup_item.setTextAlignment(1, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                subgroup_item.setData(0, ROLE_LEVEL, "subgroup")
                group_item.addChild(subgroup_item)

                # Events directly under subgroup (no subcategory level)
                event_df = subgroup_df.sort_values(
                    ["post_count", "event_tag"], ascending=[False, True]
                )
                for row in event_df.itertuples(index=False):
                    event_name = str(row.event_tag)
                    post_count = int(row.post_count)

                    ev_item = QTreeWidgetItem()
                    ev_item.setText(0, event_name)
                    ev_item.setText(1, f"{post_count:,}")
                    ev_item.setTextAlignment(1, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                    ev_item.setData(0, ROLE_LEVEL, "event")
                    ev_item.setData(0, ROLE_EVENT, event_name)

                    combo_count = int(sum(self.event_combo_index.get(event_name, {}).values()))
                    if combo_count > 0:
                        font = QFont(ev_item.font(0))
                        font.setBold(True)
                        ev_item.setFont(0, font)

                    subgroup_item.addChild(ev_item)
                    self.tree_event_items[event_name] = ev_item

        # Expand groups by default; subgroups stay collapsed
        for gi in range(self.event_tree.topLevelItemCount()):
            self.event_tree.topLevelItem(gi).setExpanded(True)

        if self.current_event:
            self._expand_path_for_event(self.current_event)

        self.event_tree.blockSignals(False)

    def _expand_path_for_event(self, event_name: str) -> None:
        if hasattr(self, 'nav_splitter'):
            return  # No-op: no tree to expand
        item = self.tree_event_items.get(str(event_name))
        while item is not None:
            item.setExpanded(True)
            item = item.parent()

    def _select_event(self, event_name: str, source: str) -> None:  # type: ignore[override]
        if hasattr(self, 'nav_splitter'):
            self.current_event = event_name
            self._select_detail_event(event_name)
            self._on_event_selected(event_name)
            return
        super()._select_event(event_name, source)
        self._expand_path_for_event(event_name)

    def _apply_filter(self, text: str) -> None:  # type: ignore[override]
        needle = text.strip().lower()
        all_events = self.events["tag_name"].astype(str).tolist()
        visible_events = self._get_visible_events_for_partition()
        filtered_events = [
            name for name in all_events if (name in visible_events) and self._matches_search(name, needle)
        ]
        if needle and filtered_events:
            def match_mode(name: str) -> int:
                lname = str(name).lower()
                if lname == needle:
                    return 0
                if lname.startswith(needle):
                    return 1
                if needle in lname:
                    return 2
                return 3

            filtered_events = sorted(
                filtered_events,
                key=lambda n: (
                    match_mode(str(n)),
                    -int(self.event_post_count_rank_map.get(str(n), 0)),
                    str(n),
                ),
            )
        else:
            filtered_events = sorted(
                filtered_events,
                key=lambda n: (-int(self.event_post_count_rank_map.get(str(n), 0)), str(n)),
            )

        # Fallback: if master-detail not yet initialized, use old behavior
        if not hasattr(self, 'nav_splitter'):
            self._refresh_event_list(filtered_events)
            self._refresh_event_tree(filtered_events)
            if filtered_events:
                if self.current_event in filtered_events:
                    self._select_event(self.current_event, source="filter")
                else:
                    self._select_event(filtered_events[0], source="filter")
            else:
                self.current_event = ""
                self.title_label.setText("No matched events")
                self.reason_label.setText("근거: -")
                self._clear_detail_views()
            return

        # Master-detail mode
        self._applying_filter = True
        try:
            # Upper navigation always refreshed
            self._refresh_subgroup_navigation(filtered_events)

            if needle:
                # Search mode: show all matching events directly (ignore subgroup)
                self._search_active = True
                self._refresh_event_detail_list(filtered_events)
            else:
                # Normal mode: subgroup-based view
                self._search_active = False
                if self._current_nav_key:
                    self._restore_subgroup_selection(self._current_nav_key)
                else:
                    self._select_first_subgroup()
        finally:
            self._applying_filter = False

        # Event selection
        if filtered_events:
            if self.current_event and self.current_event in self._detail_event_items:
                self._select_detail_event(self.current_event)
            else:
                self._select_first_detail_event()
        else:
            self.current_event = ""
            self.title_label.setText("No matched events")

    def _clear_partition_bound_tables(self) -> None:
        self.expr_table.setRowCount(0)
        self.cloth_table.setRowCount(0)
        self.color_table.setRowCount(0)
        self.combo_table.setRowCount(0)
        self.combo_info.setPlainText(
            f"Step15 partition output is not available for: {self.step15_active_partition_name or '-'}"
        )

    def _starts_with_color_prefix(self, tag_value: Any) -> bool:
        text = _norm_text(tag_value)
        if not text:
            return False
        for prefix in self.color_prefixes:
            if text.startswith(prefix + " "):
                return True
        return False

    def _hide_color_prefixed_rows(self, df: pd.DataFrame, tag_col: str) -> pd.DataFrame:
        if df.empty or tag_col not in df.columns or not self.color_prefixes:
            return df
        keep_mask = ~df[tag_col].map(self._starts_with_color_prefix).astype(bool)
        return df[keep_mask]

    def _convert_color_tab_to_characteristic(self) -> None:
        # Keep existing tab layout from step1 but rename Color -> Characteristic.
        tabs = self.findChildren(QTabWidget)
        for tab_widget in tabs:
            for i in range(tab_widget.count()):
                if tab_widget.tabText(i).strip().lower() == "color":
                    tab_widget.setTabText(i, "Characteristic")
                    self.color_table.setHorizontalHeaderLabels(["Characteristic", "Count", "Confidence", ""])
                    return
        self.color_table.setHorizontalHeaderLabels(["Characteristic", "Count", "Confidence", ""])

    def _fill_cooccurrence(
        self,
        table,
        df,
        event_col: str,
        target_col: str,
        event_id: int,
    ) -> None:
        if self.step15_active_data is None:
            if table is self.expr_table or table is self.cloth_table or table is self.color_table:
                table.setRowCount(0)
                return
            return super()._fill_cooccurrence(table, df, event_col, target_col, event_id)

        event_name = self.id_to_tag.get(int(event_id), "")
        if not event_name:
            table.setRowCount(0)
            return

        if table is self.expr_table:
            sub = (
                self.step15_active_data["expr"][self.step15_active_data["expr"]["event_tag"] == event_name]
                .sort_values(["confidence", "count", "pmi"], ascending=[False, False, False])
                .head(TOP_N)
            )
            table.setSortingEnabled(False)
            table.setRowCount(len(sub))
            for row_idx, (_, row) in enumerate(sub.iterrows()):
                table.setItem(row_idx, 0, QTableWidgetItem(str(row["expression_tag"])))
                self._set_number(table, row_idx, 1, int(row["count"]))
                self._set_number(table, row_idx, 2, round(float(row["confidence"]), 4))
            table.setSortingEnabled(True)
            table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
            return

        if table is self.cloth_table:
            base = self.step15_active_data["cloth"][
                self.step15_active_data["cloth"]["event_tag"] == event_name
            ]
            base = self._hide_color_prefixed_rows(base, "clothing_tag")
            sub = base.sort_values(["confidence", "count", "pmi"], ascending=[False, False, False]).head(TOP_N)
            table.setSortingEnabled(False)
            table.setRowCount(len(sub))
            for row_idx, (_, row) in enumerate(sub.iterrows()):
                table.setItem(row_idx, 0, QTableWidgetItem(str(row["clothing_tag"])))
                self._set_number(table, row_idx, 1, int(row["count"]))
                self._set_number(table, row_idx, 2, round(float(row["confidence"]), 4))
            table.setSortingEnabled(True)
            table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
            return

        if table is self.color_table:
            base = self.step15_active_data["char"][
                self.step15_active_data["char"]["event_tag"] == event_name
            ]
            base = self._hide_color_prefixed_rows(base, "characteristic_tag")
            sub = base.sort_values(["confidence", "count", "pmi"], ascending=[False, False, False]).head(TOP_N)
            table.setSortingEnabled(False)
            table.setRowCount(len(sub))
            for row_idx, (_, row) in enumerate(sub.iterrows()):
                table.setItem(row_idx, 0, QTableWidgetItem(str(row["characteristic_tag"])))
                self._set_number(table, row_idx, 1, int(row["count"]))
                self._set_number(table, row_idx, 2, round(float(row["confidence"]), 4))
            table.setSortingEnabled(True)
            table.sortByColumn(2, Qt.SortOrder.DescendingOrder)
            return

        return super()._fill_cooccurrence(table, df, event_col, target_col, event_id)

    def _fill_observed_combos(self, event_name: str) -> None:  # type: ignore[override]
        if self.step15_active_data is None:
            self.combo_table.setRowCount(0)
            self.combo_info.setPlainText(
                f"Step15 partition output is not available for: {self.step15_active_partition_name or '-'}"
            )
            return

        # If no staging or current event is already staged, single-event mode
        if not self.staged_events or event_name in self.staged_events:
            self._fill_observed_combos_single(event_name)
        else:
            self._fill_observed_combos_multi(event_name)

    def _fill_observed_combos_single(self, event_name: str) -> None:
        combo_df = self.step15_active_data["combo"]
        sub = combo_df[combo_df["event_tag"] == event_name].sort_values("count", ascending=False).head(TOP_N)
        total_rows = int(len(sub))

        self.combo_table.setSortingEnabled(False)
        self.combo_table.setRowCount(total_rows)
        for row_idx, (_, row) in enumerate(sub.iterrows()):
            combo_text = str(row["observed_event_combo"])
            combo_tags = {t.strip() for t in combo_text.split(",") if t.strip()}

            # Merge retained dependency tags into the combo display
            retained_dep_raw = str(row.get("retained_dependency_tags", "") or "")
            dep_tags = [t.strip() for t in retained_dep_raw.split(",") if t.strip()]
            new_deps = [t for t in dep_tags if t not in combo_tags]
            if new_deps:
                combo_text += ", " + ", ".join(f"[{t}]" for t in new_deps)

            self.combo_table.setItem(row_idx, 0, QTableWidgetItem(combo_text))
            self._set_number(self.combo_table, row_idx, 1, int(row["count"]))
        self.combo_table.setSortingEnabled(True)
        self.combo_table.sortByColumn(1, Qt.SortOrder.DescendingOrder)

    def _get_event_pair_index(self) -> set[frozenset[str]]:
        """Build a set of event pairs observed together in any combo (lazy-cached)."""
        if self._event_pair_cache is not None:
            return self._event_pair_cache
        pairs: set[frozenset[str]] = set()
        if self.step15_active_data is None:
            self._event_pair_cache = pairs
            return pairs
        combo_df = self.step15_active_data["combo"]
        for combo_text in combo_df["observed_event_combo"].astype(str):
            events = [t.strip() for t in combo_text.split(",") if t.strip()]
            for i in range(len(events)):
                for j in range(i + 1, len(events)):
                    pairs.add(frozenset({events[i], events[j]}))
        self._event_pair_cache = pairs
        return pairs

    def _fill_observed_combos_multi(self, event_name: str) -> None:
        # Collect staged combo lists that actually have data
        staged_combo_lists: list[list[tuple[frozenset[str], int]]] = []
        staged_primaries: list[str] = []
        for ev in self.staged_events:
            combos = self.staged_combos_map.get(ev, [])
            if not combos:
                continue
            staged_combo_lists.append(combos)
            staged_primaries.append(ev)

        if not staged_combo_lists:
            self._fill_observed_combos_single(event_name)
            return

        combo_df = self.step15_active_data["combo"]
        current_sub = combo_df[combo_df["event_tag"] == event_name].sort_values(
            "count", ascending=False
        ).head(TOP_N)
        current_combos: list[tuple[frozenset[str], int]] = []
        for _, row in current_sub.iterrows():
            c_text = str(row["observed_event_combo"])
            c_set = frozenset(t.strip() for t in c_text.split(",") if t.strip())
            current_combos.append((c_set, int(row["count"])))

        if not current_combos:
            self._fill_observed_combos_single(event_name)
            return

        pair_index = self._get_event_pair_index()

        # N-way cross-product: staged[0] × staged[1] × ... × current
        all_groups = staged_combo_lists + [current_combos]
        all_primaries = staged_primaries + [event_name]
        n_groups = len(all_groups)

        candidates: list[tuple[list[str], float]] = []
        seen: set[frozenset[str]] = set()

        for combo_tuple in itertools.product(*all_groups):
            merged: frozenset[str] = frozenset()
            for cs, _ in combo_tuple:
                merged = merged | cs

            if merged in seen:
                continue
            seen.add(merged)

            if len(merged) > 8:
                continue

            # Compatibility: check all cross-group event pairs
            checks = 0
            hits = 0
            for i in range(n_groups):
                for j in range(i + 1, n_groups):
                    s_i, _ = combo_tuple[i]
                    s_j, _ = combo_tuple[j]
                    primary_i = all_primaries[i]
                    primary_j = all_primaries[j]
                    companions_i = s_i - {primary_i}
                    companions_j = s_j - {primary_j}

                    for c in companions_i:
                        if c != primary_j:
                            checks += 1
                            if frozenset({c, primary_j}) in pair_index:
                                hits += 1
                    for c in companions_j:
                        if c != primary_i:
                            checks += 1
                            if frozenset({c, primary_i}) in pair_index:
                                hits += 1
                    for ci in companions_i:
                        for cj in companions_j:
                            if ci != cj:
                                checks += 1
                                if frozenset({ci, cj}) in pair_index:
                                    hits += 1

            compat = (hits / checks) if checks > 0 else 1.0

            if checks >= 2 and compat < 0.3:
                continue

            score = 1.0
            for _, cnt in combo_tuple:
                score *= float(cnt)
            score *= (0.5 + 0.5 * compat)

            candidates.append((sorted(merged), score))

        candidates.sort(key=lambda x: -x[1])
        candidates = candidates[:TOP_N]

        # Table (2-column: combo text, score)
        self.combo_table.setSortingEnabled(False)
        self.combo_table.setRowCount(len(candidates))
        for row_idx, (merged_events, score) in enumerate(candidates):
            self.combo_table.setItem(row_idx, 0, QTableWidgetItem(", ".join(merged_events)))
            self._set_number(self.combo_table, row_idx, 1, round(score, 1))
        self.combo_table.setSortingEnabled(True)
        self.combo_table.sortByColumn(1, Qt.SortOrder.DescendingOrder)

    def _render_quality(self) -> None:  # type: ignore[override]
        super()._render_quality()
        lines = self.metrics_box.toPlainText().splitlines()
        lines.append("")
        lines.append("[step15_partition_binding]")
        lines.append(f"selected_partition: {self.step15_active_partition_name or '-'}")
        lines.append(f"available_partition_outputs: {len(self.step15_available_partitions):,}")
        if self.step15_active_data is None:
            lines.append("status: missing output for selected partition")
        else:
            quality = self.step15_active_data.get("quality", {})
            observed = quality.get("observed_combo", {})
            lines.append("status: loaded")
            lines.append(f"rows_total: {int(quality.get('rows_total', 0)):,}")
            lines.append(f"event_post_coverage: {float(quality.get('coverage', {}).get('event_post_coverage', 0.0)):.4f}")
            lines.append(
                f"characteristic_post_coverage: "
                f"{float(quality.get('coverage', {}).get('characteristic_post_coverage', 0.0)):.4f}"
            )
            lines.append(f"observed_combo_rows: {int(observed.get('rows', 0)):,}")
            lines.append(f"retained_threshold: {float(observed.get('retained_threshold', 0.9))}")
        lines.append("ui_filter: hide tags starting with '{color} ' in Clothing/Characteristic tabs")
        self.metrics_box.setPlainText("\n".join(lines))


def main() -> None:
    assets, missing = load_assets()
    app = QApplication(sys.argv)
    if assets is None:
        # TODO(web-dialog): 원래 QMessageBox(Critical) "Missing files" — standalone runner 라 web shell 무관.
        # 일관성을 위해 print 로 변경.
        print(f"[Dialog/ERROR] Missing files: Step1 assets are missing.\n[detail]\n" + "\n".join(missing))
        sys.exit(1)

    viewer = PartitionBoundViewer(assets)
    viewer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()