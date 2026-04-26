"""
Event Preset Engines — 비즈니스 로직 (TaxonomyEngine, StagingEngine, RecommendationEngine, PromptBuilder)

viewer_multi.py의 핵심 알고리즘을 UI 비종속적 엔진으로 추출.
"""
from __future__ import annotations

import itertools
import lzma
import pickle
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from core.tag_search_index import TagSearchIndex

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------
TOP_N = 100
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

RATING_TOGGLES = ["General", "Sensitive", "Question", "Explicit"]
RATING_PREFIX_MAP = {
    "General": "g",
    "Sensitive": "s",
    "Question": "q",
    "Explicit": "e",
}
PREFIX_TO_RATING = {v: k for k, v in RATING_PREFIX_MAP.items()}
PERSON_PARTITION_ORDER = [
    "1girl_solo", "1girl", "1girl_1boy", "1girl_multiple_boys",
    "2girls", "multiple_girls", "1boy_solo", "1boy",
    "1boy_multiple_girls", "2boys", "multiple_boys",
    "multiple_girls_multiple_boys", "other",
]
PERSON_PARTITION_LABELS = {
    "1girl_solo": "1girl solo", "1girl": "1girl",
    "1girl_1boy": "1girl + 1boy", "1girl_multiple_boys": "1girl + multiple boys",
    "2girls": "2girls", "multiple_girls": "multiple girls",
    "1boy_solo": "1boy solo", "1boy": "1boy",
    "1boy_multiple_girls": "1boy + multiple girls",
    "2boys": "2boys", "multiple_boys": "multiple boys",
    "multiple_girls_multiple_boys": "multiple girls + multiple boys",
    "other": "other",
}
PERSON_TAG_MAP: dict[str, list[str]] = {
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
RATING_TAG_MAP: dict[str, str] = {
    "General": "general",
    "Sensitive": "sensitive",
    "Question": "questionable",
    "Explicit": "explicit",
}


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------

def split_csv(text: Any) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        return []
    return [x.strip() for x in text.split(",") if x.strip()]


def join_csv(values: set[str] | list[str]) -> str:
    if not values:
        return ""
    return ", ".join(sorted(values))


def norm_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower().replace("_", " ")
    return " ".join(text.split())


def pretty_subcategory_name(key: str) -> str:
    if not key:
        return "Unspecified"
    prefixes = [
        "holding_", "activity_", "posture_", "clothing_",
        "verb_", "gesture_", "pose_",
    ]
    for pfx in prefixes:
        if key.startswith(pfx):
            suffix = key[len(pfx):]
            if pfx == "holding_":
                return f"Holding / {suffix.replace('_', ' ').title()}"
            return suffix.replace("_", " ").title()
    return key.replace("_", " ").title()


def default_subcategory_ko_map() -> dict[str, str]:
    return {
        "activity_adjustment": "조정", "activity_apparel_adjustment": "의상 조정",
        "activity_oral_action": "구강 동작", "activity_performance": "퍼포먼스",
        "activity_locomotion": "이동", "activity_other": "기타",
        "holding_weapon": "들기 / 무기", "holding_food_drink": "들기 / 음식·음료",
        "holding_clothing": "들기 / 의상", "holding_body_self": "들기 / 신체",
        "holding_creature": "들기 / 생물", "holding_device_media": "들기 / 디바이스",
        "holding_document_sign": "들기 / 문서·표식", "holding_instrument": "들기 / 악기",
        "holding_tool_prop": "들기 / 소도구", "holding_misc": "들기 / 기타",
        "sitting": "앉기", "standing": "서기", "lying": "눕기",
        "kneeling": "무릎 꿇기", "crouching": "웅크리기", "leaning": "기대기",
        "location": "장소·위치", "posture_other": "기타 자세",
        "clothing_adjust": "정돈", "clothing_put_on": "입기",
        "clothing_lift": "올리기", "clothing_pull": "당기기",
        "clothing_aside": "젖히기", "clothing_open": "열기",
        "clothing_displaced": "흐트러짐", "clothing_remove": "벗기",
        "clothing_other": "기타 의류",
        "verb_locomotion": "이동", "verb_contact": "접촉·교류",
        "verb_eating_drinking": "먹기·마시기", "verb_sports": "운동·스포츠",
        "verb_creative": "창작·촬영", "verb_grooming": "치장·케어",
        "verb_work": "작업·가사", "verb_sound": "소리·발성",
        "verb_sleep": "수면", "verb_other": "기타 동사",
        "gesture_hand_sign": "손 기호", "gesture_arm_raise": "팔 올리기",
        "gesture_self_face": "얼굴 터치", "gesture_self_body": "몸 터치",
        "gesture_covering": "가리기", "gesture_pointing": "가리키기",
        "gesture_mouth": "입 접촉", "gesture_touch_other": "타인 접촉",
        "gesture_hair": "머리카락", "gesture_weapon": "무기·전투",
        "gesture_clothing": "의류 조정", "gesture_expressive": "표현·인사",
        "gesture_other": "기타 제스처",
        "pose_between": "사이 배치", "pose_on_body": "신체 위",
        "pose_body_display": "신체 강조", "pose_arm_rest": "팔 받침",
        "pose_feet_legs": "발·다리", "pose_surface": "표면 접촉",
        "pose_acrobatic": "아크로바틱", "pose_in_container": "용기 안",
        "pose_carrying": "운반·밀착", "pose_restraint": "구속·제압",
        "pose_resting": "안정·휴식", "pose_other": "기타 포즈",
    }


def parse_partition_name(partition_name: str) -> tuple[str, str]:
    """'g_1girl_solo' → ('g', '1girl_solo')"""
    idx = partition_name.index("_")
    return partition_name[:idx], partition_name[idx + 1:]


def format_count(n: int) -> str:
    """315444 → '315k', 150 → '150'"""
    if n >= 1000:
        return f"{n // 1000:,}k"
    return str(n)


# =========================================================================
# TaxonomyEngine
# =========================================================================

class TaxonomyEngine:
    """택소노미 인덱스, 트리 프로젝션, 검색 필터링."""

    def __init__(self, assets: dict[str, Any]):
        self.catalog = assets["tag_catalog.parquet"]
        self.category = assets["tag_category.parquet"]

        self.id_to_tag = dict(zip(self.catalog["tag_id"], self.catalog["tag_name"]))
        self.events = self.category[self.category["is_event"] == True].copy().sort_values("tag_name")
        self.event_name_to_id = dict(zip(self.events["tag_name"], self.events["tag_id"]))

        # step3 데이터
        self.mats = assets.get("step3::event_min_ancestor_set.parquet")
        self.event_prompt = assets.get("step3::event_prompt_only.parquet")

        self.root_anc_map: dict[str, set[str]] = {}
        self.all_anc_map: dict[str, set[str]] = {}
        self.event_combo_index: dict[str, Counter[tuple[str, ...]]] = {}
        self.event_post_count_map: dict[str, int] = {}
        self.event_post_count_rank_map: dict[str, int] = {}

        self.search_blob_map: dict[str, str] = {}
        self.group_display_map: dict[str, str] = {}
        self.subgroup_display_map: dict[str, str] = {}
        self.subcategory_display_map: dict[str, str] = {}
        self._tag_search_index: TagSearchIndex | None = None

        self.taxonomy: pd.DataFrame = pd.DataFrame()
        self._base_taxonomy: pd.DataFrame = pd.DataFrame()
        self._base_event_post_count_rank_map: dict[str, int] = {}

        # 인덱스 준비
        self._prepare_step3_indexes(assets)
        self._prepare_taxonomy_indexes(assets)
        self._tag_search_index = TagSearchIndex.from_event_preset_assets(
            assets,
            taxonomy=self.taxonomy,
        )
        self._base_taxonomy = self.taxonomy.copy()
        self._base_event_post_count_rank_map = dict(self.event_post_count_rank_map)

    def _prepare_step3_indexes(self, assets: dict[str, Any]) -> None:
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

    def _prepare_taxonomy_indexes(self, assets: dict[str, Any]) -> None:
        taxonomy_v2_1 = assets.get("step10::event_taxonomy_v2_1.parquet")
        taxonomy_v2 = assets.get("step10::event_taxonomy_v2.parquet")
        taxonomy_v9 = assets.get("step9::event_taxonomy_enriched.parquet")
        taxonomy_v7 = assets.get("step7::event_taxonomy.parquet")
        group_mapping = assets.get("step7::event_group_mapping.json")
        subcategory_ko = assets.get("step10::subcategory_display_ko.json", {})

        # 택소노미 우선순위: v2_1 > v2 > v9 > v7
        taxonomy = None
        for candidate in [taxonomy_v2_1, taxonomy_v2, taxonomy_v9, taxonomy_v7]:
            if candidate is not None and len(candidate) > 0:
                taxonomy = candidate
                break

        # 한글 맵 병합
        if not isinstance(subcategory_ko, dict):
            subcategory_ko = {}
        merged_ko = default_subcategory_ko_map()
        merged_ko.update({str(k): str(v) for k, v in subcategory_ko.items()})
        self._subcategory_ko_map = merged_ko

        # 그룹 디스플레이 이름
        if group_mapping:
            for group, meta in group_mapping.get("groups", {}).items():
                self.group_display_map[group] = str(meta.get("display_en", group))
            for subgroup, meta in group_mapping.get("subgroups", {}).items():
                self.subgroup_display_map[subgroup] = str(meta.get("display_en", subgroup))

        # 택소노미 없으면 폴백 생성
        if taxonomy is None or len(taxonomy) == 0:
            rows = []
            for event_name in self.events["tag_name"].astype(str).tolist():
                rows.append({
                    "event_tag": event_name,
                    "group": "expression action",
                    "group_order": 0,
                    "subgroup": "activity",
                    "subgroup_order": 0,
                    "post_count": int(self.event_post_count_map.get(event_name, 0)),
                    "root_ancestor_count": int(len(self.root_anc_map.get(event_name, set()))),
                    "search_blob": event_name,
                })
            taxonomy = pd.DataFrame(rows)

        taxonomy = taxonomy.copy()
        taxonomy["event_tag"] = taxonomy["event_tag"].astype(str)

        for col, default in [
            ("group", "expression action"), ("subgroup", "activity"),
            ("group_order", 0), ("subgroup_order", 0),
            ("post_count", 0), ("root_ancestor_count", 0),
            ("activity_subcategory", ""), ("activity_subcategory_order", 999),
        ]:
            if col not in taxonomy.columns:
                taxonomy[col] = default

        if "subcategory" not in taxonomy.columns:
            taxonomy["subcategory"] = taxonomy["activity_subcategory"].astype(str)
        if "subcategory_order" not in taxonomy.columns:
            taxonomy["subcategory_order"] = taxonomy["activity_subcategory_order"]
        if "search_blob" not in taxonomy.columns:
            taxonomy["search_blob"] = taxonomy["event_tag"]

        taxonomy["group_order"] = pd.to_numeric(taxonomy["group_order"], errors="coerce").fillna(0).astype(int)
        taxonomy["subgroup_order"] = pd.to_numeric(taxonomy["subgroup_order"], errors="coerce").fillna(0).astype(int)
        taxonomy["post_count"] = pd.to_numeric(taxonomy["post_count"], errors="coerce").fillna(0).astype(int)
        taxonomy["root_ancestor_count"] = pd.to_numeric(taxonomy["root_ancestor_count"], errors="coerce").fillna(0).astype(int)
        taxonomy["activity_subcategory"] = taxonomy["activity_subcategory"].astype(str)
        taxonomy["activity_subcategory_order"] = pd.to_numeric(
            taxonomy["activity_subcategory_order"], errors="coerce"
        ).fillna(999).astype(int)
        taxonomy["subcategory"] = taxonomy["subcategory"].astype(str).replace("nan", "")
        taxonomy["subcategory_order"] = pd.to_numeric(
            taxonomy["subcategory_order"], errors="coerce"
        ).fillna(999).astype(int)

        for row in taxonomy.itertuples(index=False):
            event_tag = str(row.event_tag)
            self.search_blob_map[event_tag] = str(getattr(row, "search_blob", event_tag)).lower()
            self.event_post_count_rank_map[event_tag] = int(getattr(row, "post_count", 0) or 0)
            subcat_key = str(getattr(row, "subcategory", "") or "")
            if subcat_key and subcat_key not in self.subcategory_display_map:
                en = pretty_subcategory_name(subcat_key)
                ko = self._subcategory_ko_map.get(subcat_key, "")
                self.subcategory_display_map[subcat_key] = f"{en} ({ko})" if ko else en

        self.taxonomy = taxonomy

    def apply_partition_projection(self, event_count_map: dict[str, int]) -> None:
        """파티션별 이벤트 카운트 기반 트리 재정렬."""
        tx = self._base_taxonomy.copy()
        tx["post_count"] = tx["event_tag"].map(lambda t: int(event_count_map.get(str(t), 0)))

        if len(tx) > 0:
            # 그룹별 합산 정렬
            group_sum = tx.groupby("group")["post_count"].sum().sort_values(ascending=False)
            group_rank = {g: i for i, g in enumerate(group_sum.index.tolist())}
            tx["group_order"] = tx["group"].map(lambda g: int(group_rank.get(g, 999))).astype(int)

            # 서브그룹별 정렬
            subgroup_sum = tx.groupby(["group", "subgroup"])["post_count"].sum().sort_values(ascending=False)
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

            # 서브카테고리별 정렬
            if "subcategory" in tx.columns:
                subcat_sum = tx.groupby(["group", "subgroup", "subcategory"])["post_count"].sum().sort_values(ascending=False)
                subcat_rank: dict[tuple[str, str, str], int] = {}
                seen_by_bucket: dict[tuple[str, str], int] = {}
                for group, subgroup, subcat in subcat_sum.index.tolist():
                    bucket = (group, subgroup)
                    cur = seen_by_bucket.get(bucket, 0)
                    subcat_rank[(group, subgroup, subcat)] = cur
                    seen_by_bucket[bucket] = cur + 1
                tx["subcategory_order"] = tx.apply(
                    lambda r: int(subcat_rank.get(
                        (str(r["group"]), str(r["subgroup"]), str(r.get("subcategory", ""))), 999,
                    )),
                    axis=1,
                )

        self.taxonomy = tx
        self.event_post_count_rank_map = {
            event: int(event_count_map.get(str(event), 0))
            for event in self.events["tag_name"].astype(str).tolist()
        }

    def reset_to_base(self) -> None:
        """파티션 프로젝션 해제, 기본 택소노미로 복원."""
        self.taxonomy = self._base_taxonomy.copy()
        self.event_post_count_rank_map = dict(self._base_event_post_count_rank_map)

    def filter_events(self, query: str) -> list[str]:
        """검색어 기반 이벤트 필터링."""
        if not query.strip():
            return self.taxonomy["event_tag"].tolist()
        if self._tag_search_index is not None:
            matches = self._tag_search_index.search_tags(
                query,
                require_event=True,
                limit=None,
            )
            if matches:
                return matches

        q = norm_text(query)
        return [
            tag for tag, blob in self.search_blob_map.items()
            if q in blob or q in norm_text(tag)
        ]

    def get_subgroups_sorted(self) -> list[dict]:
        """
        정렬된 Group → Subgroup 트리 데이터.
        Returns: [{'group': str, 'group_display': str, 'subgroup': str, 'subgroup_display': str, 'post_count': int}]
        """
        if self.taxonomy.empty:
            return []

        tx = self.taxonomy
        groups_data = tx.groupby(["group", "group_order", "subgroup", "subgroup_order"]).agg(
            post_count=("post_count", "sum")
        ).reset_index().sort_values(["group_order", "subgroup_order"])

        result = []
        for _, r in groups_data.iterrows():
            group = str(r["group"])
            subgroup = str(r["subgroup"])
            result.append({
                "group": group,
                "group_display": self.group_display_map.get(group, group.replace("_", " ").title()),
                "subgroup": subgroup,
                "subgroup_display": self.subgroup_display_map.get(subgroup, subgroup.replace("_", " ").title()),
                "post_count": int(r["post_count"]),
            })
        return result

    def get_events_for_subgroup(self, group: str, subgroup: str) -> list[dict]:
        """
        특정 서브그룹의 이벤트 목록 (서브카테고리별 그룹핑, 정렬).
        Returns: [{'event_tag': str, 'post_count': int, 'subcategory': str, 'subcategory_display': str}]
        """
        tx = self.taxonomy
        sub = tx[(tx["group"] == group) & (tx["subgroup"] == subgroup)].copy()
        sub = sub.sort_values(["subcategory_order", "post_count"], ascending=[True, False])

        result = []
        for _, r in sub.iterrows():
            event_tag = str(r["event_tag"])
            subcat = str(r.get("subcategory", "") or "")
            result.append({
                "event_tag": event_tag,
                "post_count": self.event_post_count_rank_map.get(event_tag, int(r["post_count"])),
                "subcategory": subcat,
                "subcategory_display": self.subcategory_display_map.get(subcat, ""),
            })
        return result


# =========================================================================
# StagingEngine
# =========================================================================

class StagingEngine:
    """이벤트 스테이징, 콤보 교차, 호환성 체크."""

    def __init__(self):
        self.staged_events: list[str] = []
        self.staged_combos_map: dict[str, list[tuple[frozenset[str], int]]] = {}
        self._event_pair_cache: set[frozenset[str]] | None = None

    def stage_event(self, event_name: str, combo_df: pd.DataFrame) -> bool:
        """이벤트 스테이징. 성공 시 True."""
        if event_name in self.staged_events or len(self.staged_events) >= MAX_STAGED:
            return False
        self.staged_events.append(event_name)
        self._event_pair_cache = None

        sub = combo_df[combo_df["event_tag"] == event_name].sort_values(
            "count", ascending=False
        ).head(STAGED_COMBO_TOP_N)
        combos: list[tuple[frozenset[str], int]] = []
        for _, row in sub.iterrows():
            combo_text = str(row["observed_event_combo"])
            combo_set = frozenset(t.strip() for t in combo_text.split(",") if t.strip())
            combos.append((combo_set, int(row["count"])))
        self.staged_combos_map[event_name] = combos
        return True

    def unstage_event(self, event_name: str) -> bool:
        """이벤트 스테이지 해제. 성공 시 True."""
        if event_name not in self.staged_events:
            return False
        self.staged_events.remove(event_name)
        self.staged_combos_map.pop(event_name, None)
        self._event_pair_cache = None
        return True

    def clear_staging(self):
        self.staged_events.clear()
        self.staged_combos_map.clear()
        self._event_pair_cache = None

    def is_staged(self, event_name: str) -> bool:
        return event_name in self.staged_events

    def build_event_pair_index(self, combo_df: pd.DataFrame) -> set[frozenset[str]]:
        """콤보 DF에서 모든 이벤트 쌍 인덱스 구축 (캐시)."""
        if self._event_pair_cache is not None:
            return self._event_pair_cache
        pairs: set[frozenset[str]] = set()
        for combo_text in combo_df["observed_event_combo"].astype(str):
            events = [t.strip() for t in combo_text.split(",") if t.strip()]
            for i in range(len(events)):
                for j in range(i + 1, len(events)):
                    pairs.add(frozenset({events[i], events[j]}))
        self._event_pair_cache = pairs
        return pairs

    def check_deadlock(self, pair_index: set[frozenset[str]]) -> list[tuple[str, str]]:
        """스테이징된 이벤트 중 호환 불가 쌍 검출."""
        if len(self.staged_events) < 2:
            return []
        bad = []
        for i in range(len(self.staged_events)):
            for j in range(i + 1, len(self.staged_events)):
                if frozenset({self.staged_events[i], self.staged_events[j]}) not in pair_index:
                    bad.append((self.staged_events[i], self.staged_events[j]))
        return bad

    def get_single_event_combos(
        self, event_name: str, combo_df: pd.DataFrame,
        limit: int | None = TOP_N,
    ) -> list[tuple[str, int]]:
        """단일 이벤트의 콤보 목록."""
        sub = combo_df[combo_df["event_tag"] == event_name].sort_values("count", ascending=False)
        if limit is not None:
            sub = sub.head(limit)
        result = []
        for _, row in sub.iterrows():
            combo_text = str(row["observed_event_combo"])
            combo_tags = {t.strip() for t in combo_text.split(",") if t.strip()}
            retained_dep_raw = str(row.get("retained_dependency_tags", "") or "")
            dep_tags = [t.strip() for t in retained_dep_raw.split(",") if t.strip()]
            new_deps = [t for t in dep_tags if t not in combo_tags]
            if new_deps:
                combo_text += ", " + ", ".join(f"[{t}]" for t in new_deps)
            result.append((combo_text, int(row["count"])))
        return result

    def get_multi_event_combos(
        self, event_name: str, combo_df: pd.DataFrame,
        limit: int | None = TOP_N,
    ) -> list[tuple[str, float]]:
        """N-way cross-product 콤보 교차 (스테이징 + 현재 이벤트)."""
        staged_combo_lists: list[list[tuple[frozenset[str], int]]] = []
        staged_primaries: list[str] = []
        for ev in self.staged_events:
            combos = self.staged_combos_map.get(ev, [])
            if not combos:
                continue
            staged_combo_lists.append(combos)
            staged_primaries.append(ev)

        if not staged_combo_lists:
            return []

        # 현재 이벤트의 콤보
        current_sub = combo_df[combo_df["event_tag"] == event_name].sort_values(
            "count", ascending=False
        )
        if limit is not None:
            current_sub = current_sub.head(limit)
        current_combos: list[tuple[frozenset[str], int]] = []
        for _, row in current_sub.iterrows():
            c_text = str(row["observed_event_combo"])
            c_set = frozenset(t.strip() for t in c_text.split(",") if t.strip())
            current_combos.append((c_set, int(row["count"])))

        if not current_combos:
            return []

        pair_index = self.build_event_pair_index(combo_df)

        all_groups = staged_combo_lists + [current_combos]
        all_primaries = staged_primaries + [event_name]
        n_groups = len(all_groups)

        candidates: list[tuple[list[str], float]] = []
        seen: set[frozenset[str]] = set()

        for combo_tuple in itertools.product(*all_groups):
            merged: frozenset[str] = frozenset()
            for cs, _ in combo_tuple:
                merged = merged | cs

            if merged in seen or len(merged) > 8:
                continue
            seen.add(merged)

            # 호환성 점수
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
        if limit is not None:
            candidates = candidates[:limit]
        return [(", ".join(evts), sc) for evts, sc in candidates]


# =========================================================================
# RecommendationEngine
# =========================================================================

class RecommendationEngine:
    """추천 태그 관리 — 공기 태그 쿼리/병합, 칩 상태, 자동 의존성."""

    def __init__(self, recommendations: dict, color_prefixes: list[str]):
        self._recommendations = recommendations
        self._color_prefixes = color_prefixes
        self._cooc_cache: dict[str, dict[str, list[tuple[str, float]]]] = {}
        self.auto_dep_tags: list[str] = []
        self.active_rec_tags: dict[str, bool] = {}

        # 색상 접두사 regex 사전 컴파일 (벡터화용)
        if color_prefixes:
            escaped = [re.escape(p) for p in color_prefixes]
            self._color_re = re.compile(r"^(?:" + "|".join(escaped) + r")[\s_]", re.IGNORECASE)
        else:
            self._color_re = None

        # 파티션별 event_tag 인덱스 + affinity 인덱스
        self._partition_index: dict[str, dict[str, pd.DataFrame]] = {}
        self._affinity_index: dict[str, dict[str, set[str]]] | None = None
        self._affinity_partition_id: str = ""

    def collect_auto_deps(self, event_names: list[str]) -> list[str]:
        """추천 JSON에서 자동 삽입 의존성 태그 수집."""
        event_set = set(event_names)
        seen: set[str] = set()
        deps: list[str] = []
        for ev in event_names:
            rec = self._recommendations.get(ev)
            if rec is None:
                continue
            for key in ("object_tags", "clothing_tags"):
                for t in rec.get(key, []):
                    tag = t["tag"]
                    if tag not in seen and tag not in event_set:
                        seen.add(tag)
                        deps.append(tag)
        self.auto_dep_tags = deps
        return deps

    def get_hierarchy_info(self, event_names: list[str]) -> tuple[str | None, str | None]:
        """추천 JSON에서 계층 parent/root 추출."""
        parent = None
        root = None
        for ev in event_names:
            rec = self._recommendations.get(ev)
            if rec is None:
                continue
            if parent is None and rec.get("hierarchy_parent"):
                parent = rec["hierarchy_parent"]
            if root is None and rec.get("hierarchy_root"):
                root = rec["hierarchy_root"]
        return parent, root

    def _get_event_group(
        self, partition_data: dict[str, Any], df_key: str, event_name: str,
    ) -> pd.DataFrame:
        """event_tag 기준 그룹 인덱스에서 빠르게 서브셋 반환."""
        pid = id(partition_data)
        cache_key = f"{pid}:{df_key}"
        if cache_key not in self._partition_index:
            df = partition_data.get(df_key, pd.DataFrame())
            if df.empty:
                self._partition_index[cache_key] = {}
            else:
                self._partition_index[cache_key] = {
                    name: group for name, group in df.groupby("event_tag", sort=False)
                }
        groups = self._partition_index[cache_key]
        return groups.get(event_name, pd.DataFrame())

    def query_cooccurrence(
        self, event_name: str, partition_data: dict[str, Any],
    ) -> dict[str, list[tuple[str, float]]]:
        """단일 이벤트의 공기 태그 쿼리 (파티션 데이터 기반, 캐시)."""
        if event_name in self._cooc_cache:
            return self._cooc_cache[event_name]

        result: dict[str, list[tuple[str, float]]] = {"expr": [], "cloth": [], "char": []}

        # Expression
        sub = self._get_event_group(partition_data, "expression", event_name)
        if not sub.empty:
            sub = sub[sub["confidence"] >= COOC_EXPR_CONFIDENCE_MIN]
            sub = sub.nlargest(COOC_TOP_N_PER_EVENT, "confidence")
            result["expr"] = list(zip(
                sub["expression_tag"].astype(str), sub["confidence"].astype(float),
            ))

        # Clothing (색상 필터링)
        sub = self._get_event_group(partition_data, "clothing", event_name)
        if not sub.empty:
            sub = self._hide_color_prefixed(sub, "clothing_tag")
            sub = sub[sub["confidence"] >= COOC_CLOTH_CONFIDENCE_MIN]
            sub = sub.nlargest(COOC_TOP_N_PER_EVENT, "confidence")
            result["cloth"] = list(zip(
                sub["clothing_tag"].astype(str), sub["confidence"].astype(float),
            ))

        # Characteristic (색상 필터링)
        sub = self._get_event_group(partition_data, "characteristic", event_name)
        if not sub.empty:
            sub = self._hide_color_prefixed(sub, "characteristic_tag")
            sub = sub[sub["confidence"] >= COOC_CHAR_CONFIDENCE_MIN]
            sub = sub.nlargest(COOC_TOP_N_PER_EVENT, "confidence")
            result["char"] = list(zip(
                sub["characteristic_tag"].astype(str), sub["confidence"].astype(float),
            ))

        self._cooc_cache[event_name] = result
        return result

    def merge_cooccurrence(
        self, event_names: list[str], partition_data: dict[str, Any],
        affinity_events: set[str] | None = None,
    ) -> dict[str, list[tuple[str, float]]]:
        """여러 이벤트의 공기 태그 병합 (union with max confidence)."""
        if affinity_events is not None:
            filtered = [ev for ev in event_names if ev in affinity_events]
            query_events = filtered if filtered else event_names
        else:
            query_events = event_names

        auto_dep_set = set(self.auto_dep_tags)
        merged: dict[str, dict[str, float]] = {"expr": {}, "cloth": {}, "char": {}}

        for ev in query_events:
            per_event = self.query_cooccurrence(ev, partition_data)
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

    def _ensure_affinity_index(self, partition_data: dict[str, Any]) -> None:
        """역방향 affinity 인덱스 구축 (tag → event set), 파티션 변경 시만 재구축."""
        pid = id(partition_data)
        if self._affinity_index is not None and self._affinity_partition_id == pid:
            return

        index: dict[str, set[str]] = defaultdict(set)
        cat_map = [
            ("expression_tag", "expression"),
            ("clothing_tag", "clothing"),
            ("characteristic_tag", "characteristic"),
        ]
        for tag_col, df_key in cat_map:
            df = partition_data.get(df_key, pd.DataFrame())
            if df.empty or tag_col not in df.columns:
                continue
            above = df[df["confidence"] >= COOC_AFFINITY_THRESHOLD]
            for tag_val, evt in zip(above[tag_col], above["event_tag"]):
                index[str(tag_val)].add(str(evt))

        self._affinity_index = dict(index)
        self._affinity_partition_id = pid

    def get_affinity_events(
        self, selected_tags: list[str], partition_data: dict[str, Any],
    ) -> set[str] | None:
        """역방향 lookup: 선택된 태그가 높은 공기도를 가진 이벤트 집합."""
        if not selected_tags:
            return None

        self._ensure_affinity_index(partition_data)
        assert self._affinity_index is not None

        affinity: set[str] | None = None
        for tag in selected_tags:
            tag_events = self._affinity_index.get(tag, set())
            affinity = tag_events if affinity is None else (affinity & tag_events)
        return affinity if affinity else None

    def get_active_tags(self) -> list[str]:
        return [tag for tag, on in self.active_rec_tags.items() if on]

    def set_chip_state(self, tag: str, checked: bool):
        self.active_rec_tags[tag] = checked

    def reset_states(self):
        self.active_rec_tags.clear()
        self._cooc_cache.clear()
        self._partition_index.clear()
        self._affinity_index = None

    def clear_cache(self):
        self._cooc_cache.clear()
        self._partition_index.clear()
        self._affinity_index = None

    def _hide_color_prefixed(self, df: pd.DataFrame, col: str) -> pd.DataFrame:
        """색상 접두사가 붙은 태그 행 제거 (벡터화)."""
        if df.empty or self._color_re is None:
            return df
        normed = df[col].astype(str).str.strip().str.lower().str.replace("_", " ", regex=False)
        mask = ~normed.str.contains(self._color_re)
        return df[mask]


# =========================================================================
# PromptBuilder
# =========================================================================

class PromptBuilder:
    """프롬프트 조립."""

    @staticmethod
    def build(
        person_category: str,
        rating: str,
        event_names: list[str],
        auto_dep_tags: list[str],
        active_rec_tags: list[str],
    ) -> str:
        """이벤트 + 의존성 + 추천 태그 → 프롬프트 문자열."""
        person_tags = PERSON_TAG_MAP.get(person_category, [])
        rating_tag = RATING_TAG_MAP.get(rating, "")

        event_set = set(event_names)
        unique_deps = [t for t in auto_dep_tags if t not in event_set]
        all_used = event_set | set(unique_deps)
        unique_recs = [t for t in active_rec_tags if t not in all_used]

        parts = (
            list(person_tags)
            + ([rating_tag] if rating_tag else [])
            + event_names
            + unique_deps
            + unique_recs
        )
        return ", ".join(parts)

    @staticmethod
    def parse_combo_events(combo_text: str) -> list[str]:
        """콤보 텍스트에서 이벤트명 추출 ([] 브래킷 처리)."""
        clean = []
        for ev in (t.strip() for t in combo_text.split(",") if t.strip()):
            if ev.startswith("[") and ev.endswith("]"):
                clean.append(ev[1:-1])
            else:
                clean.append(ev)
        return clean


# =========================================================================
# QuickSearchComboProvider
# =========================================================================

class QuickSearchComboProvider:
    """Quick Search .tgp 파티션에서 raw 콤보 추출 (Full Mode 전용).

    data/quick_search/ 가 존재하는 경우에만 사용 가능.
    ``try_create()`` 팩토리로 생성하며, 데이터 미설치 시 ``None`` 반환.

    필터링: 이벤트 태그 + 이벤트-앵커 의존성/부모 태그만 허용 (allowlist).
    """

    QUICK_SEARCH_DIR = Path("data/quick_search")
    METADATA_FILE = QUICK_SEARCH_DIR / "metadata.tgpm"
    _TGPS_MAGIC = b"TGPS"
    RAW_COMBO_LIMIT = 1000

    def __init__(self) -> None:
        self._tag_to_id: dict[str, int] = {}
        self._id_to_tag: dict[int, str] = {}
        self._allow_set: set[str] = set()
        self._partition_cache: dict[str, Any] = {}  # partition_name → store

    # ------------------------------------------------------------------
    # 팩토리
    # ------------------------------------------------------------------

    @classmethod
    def try_create(
        cls,
        category_df: pd.DataFrame,
        dependency_df: pd.DataFrame | None = None,
    ) -> "QuickSearchComboProvider | None":
        """Quick Search 데이터 존재 확인 + 초기화. 사용 불가면 None."""
        provider = cls()
        if not provider._check_availability():
            return None
        if not provider._load_metadata():
            return None
        provider._build_allowlist(category_df, dependency_df)
        return provider

    # ------------------------------------------------------------------
    # 내부 초기화
    # ------------------------------------------------------------------

    def _check_availability(self) -> bool:
        if not self.QUICK_SEARCH_DIR.exists():
            return False
        if not self.METADATA_FILE.exists():
            return False
        tgp_count = sum(1 for _ in self.QUICK_SEARCH_DIR.glob("*.tgp"))
        if tgp_count < 10:
            return False
        return True

    def _load_metadata(self) -> bool:
        """metadata.tgpm → tag_to_id, id_to_tag."""
        try:
            with open(self.METADATA_FILE, "rb") as f:
                magic = f.read(4)
                if magic != self._TGPS_MAGIC:
                    return False
                _ = struct.unpack("<H", f.read(2))[0]
                clen = struct.unpack("<I", f.read(4))[0]
                compressed = f.read(clen)
            data = pickle.loads(lzma.decompress(compressed))
            raw_t2i = data.get("tag_to_id", {})
            if len(raw_t2i) <= 13053:
                return False
            self._tag_to_id = {norm_text(k): int(v) for k, v in raw_t2i.items()}
            self._id_to_tag = {
                int(k): norm_text(v)
                for k, v in data.get("id_to_tag", {}).items()
            }
            return True
        except Exception as exc:
            print(f"[EventPreset/QS] metadata load failed: {exc}")
            return False

    def _build_allowlist(
        self,
        category_df: pd.DataFrame,
        dependency_df: pd.DataFrame | None = None,
    ) -> None:
        """이벤트 태그 + 이벤트-앵커 의존성/부모 태그 allowlist 구축.

        Codex query_quick_search_full_mode.py의 load_allowlist_sets() 로직 이식:
        1. event_set: tag_category.parquet is_event == True
        2. dependency_set: dependency_rules.parquet에서 이벤트-앵커 행의 child/parent 태그
        3. allow_set = event_set | dependency_set
        """
        # 1) 이벤트 태그 세트
        event_set: set[str] = set()
        if "is_event" in category_df.columns:
            event_set.update(
                norm_text(t) for t in
                category_df.loc[category_df["is_event"] == True, "tag_name"]
            )

        # 2) 이벤트-앵커 의존성 태그
        dependency_set: set[str] = set()
        if dependency_df is not None and not dependency_df.empty:
            dep = dependency_df.copy()
            for col in ("child_tag", "parent_tag"):
                if col in dep.columns:
                    dep[col] = dep[col].astype(str).map(norm_text)

            # 이벤트 카테고리 or 이벤트 태그에 연결된 행만 유지
            masks = []
            if "child_category" in dep.columns:
                masks.append(dep["child_category"].astype(str) == "event")
            if "parent_category" in dep.columns:
                masks.append(dep["parent_category"].astype(str) == "event")
            if "child_tag" in dep.columns:
                masks.append(dep["child_tag"].isin(event_set))
            if "parent_tag" in dep.columns:
                masks.append(dep["parent_tag"].isin(event_set))

            if masks:
                combined_mask = masks[0]
                for m in masks[1:]:
                    combined_mask = combined_mask | m
                dep_event = dep[combined_mask]

                if "child_tag" in dep_event.columns:
                    dependency_set.update(dep_event["child_tag"].tolist())
                if "parent_tag" in dep_event.columns:
                    dependency_set.update(dep_event["parent_tag"].tolist())

        self._allow_set = event_set | dependency_set
        # 빈 문자열 제거
        self._allow_set.discard("")

    # ------------------------------------------------------------------
    # 파티션 스토어
    # ------------------------------------------------------------------

    def _get_store(self, partition_name: str) -> Any | None:
        """파티션 스토어 lazy load + 캐시."""
        if partition_name in self._partition_cache:
            store = self._partition_cache[partition_name]
            return store if getattr(store, "_loaded", False) else None

        tgp_path = self.QUICK_SEARCH_DIR / f"{partition_name}.tgp"
        if not tgp_path.exists():
            return None

        try:
            from ui.interactive.quick_search_data import SinglePartitionStore
            store = SinglePartitionStore.load(str(tgp_path))
        except Exception:
            return None

        self._partition_cache[partition_name] = store
        return store if getattr(store, "_loaded", False) else None

    # ------------------------------------------------------------------
    # 콤보 조회
    # ------------------------------------------------------------------

    def get_combos(
        self, event_name: str, partition_name: str,
    ) -> list[tuple[str, int]]:
        """Quick Search에서 event_name 콤보 추출.

        Returns:
            빈도 내림차순 ``[(combo_text, count), ...]``, 최대 RAW_COMBO_LIMIT 개.
            데이터 없으면 빈 리스트.
        """
        store = self._get_store(partition_name)
        if store is None:
            return []

        # event_name은 이미 스페이스 포맷, tag_to_id도 norm_text 적용 완료
        if event_name not in self._tag_to_id:
            return []

        indices = store.filter_events(
            required_tags=[event_name],
            excluded_tags=None,
            tag_to_id=self._tag_to_id,
        )
        if len(indices) == 0:
            return []

        # CSR 버퍼에서 이벤트별 태그 추출 + allowlist 필터 + 집계
        combo_counter: Counter[tuple[str, ...]] = Counter()
        indptr = store._event_tag_indptr
        tag_indices = store._event_tag_indices
        id_to_tag = self._id_to_tag
        allow_set = self._allow_set

        for evt_idx in indices:
            start = int(indptr[int(evt_idx)])
            end = int(indptr[int(evt_idx) + 1])

            kept: list[str] = []
            for tid in tag_indices[start:end]:
                name = id_to_tag.get(int(tid))
                if not name:
                    continue
                if name not in allow_set:
                    continue
                kept.append(name)

            if kept:
                combo_counter[tuple(sorted(set(kept)))] += 1

        if not combo_counter:
            return []

        return [
            (", ".join(combo), count)
            for combo, count in combo_counter.most_common(self.RAW_COMBO_LIMIT)
        ]
