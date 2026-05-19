"""
Clothes Preset Engines — 비즈니스 로직 (택소노미, 규칙, 표현, 프롬프트)

viewer_clothes.py의 핵심 알고리즘을 4개 엔진 클래스로 분리.
패턴 참조: ui/event_preset/engines.py
"""
from __future__ import annotations

from collections import defaultdict
from math import ceil
from typing import Any

from .data_manager import (
    REGIONS,
    ComboSummary,
    RegionTag,
    norm_text,
    parse_csv_tags,
    unique_preserve,
)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

DISPLAY_SLOTS = [
    "HEAD_NECK_FACE", "UPPER_BODY", "WAIST_HIP",
    "ARMS_HANDS", "LEGS_FEET", "STYLE",
]

SLOT_LABELS = {
    "HEAD_NECK_FACE": "Head / Neck / Face",
    "UPPER_BODY": "Upper Body",
    "WAIST_HIP": "Waist / Hip",
    "ARMS_HANDS": "Arms / Hands",
    "LEGS_FEET": "Legs / Feet",
    "STYLE": "Style",
}

REGION_LABELS = {
    "HEAD_NECK_FACE": "Head / Neck / Face",
    "UPPER_BODY": "Upper Body",
    "WAIST_HIP": "Waist / Hip",
    "ARMS_HANDS": "Arms / Hands",
    "LEGS": "Legs",
    "FEET": "Feet",
}

PAIR_MODE_PROFILES: dict[str, dict[str, float | int]] = {
    "Strict": {"pair_min_conf": 0.003, "pair_min_count": 100, "pair_min_lift": 0.0},
    "Balanced": {"pair_min_conf": 0.0015, "pair_min_count": 50, "pair_min_lift": 0.0},
    "Explore": {"pair_min_conf": 0.0, "pair_min_count": 30, "pair_min_lift": 0.0},
}

LOW_LIFT_ALERT_LIFT_MAX = 0.30
LOW_LIFT_IGNORE_PAIRCOUNT_MIN = 200
LOW_LIFT_CARE_CONF_MAX = 0.03

MAX_ROWS_PER_REGION = 500
MAX_COMBO_ROWS_DISPLAY = 3000
SEARCH_DEBOUNCE_MS = 180


# ---------------------------------------------------------------------------
# ClothingTaxonomyEngine — 슬롯 할당 + 리전 매핑 + 서브그룹 분류
# ---------------------------------------------------------------------------

class ClothingTaxonomyEngine:
    """region_tags → (slot, display_subgroup) 매핑을 담당.

    소스: viewer_clothes.py L1268-1468
    """

    def rebuild_slot_assignment(
        self,
        region_tags: list[RegionTag],
    ) -> dict[str, Any]:
        """region_tags에서 슬롯/그룹/행 할당을 재계산.

        Returns dict with keys:
            assigned_slot_by_tag, assigned_group_by_tag,
            assigned_row_by_tag, slot_rows_cache
        """
        by_tag: dict[str, RegionTag] = {}
        for r in region_tags:
            key = norm_text(r.tag)
            if not key:
                continue
            prev = by_tag.get(key)
            if prev is None or int(r.post_count) > int(prev.post_count):
                by_tag[key] = r

        assigned_slot: dict[str, str] = {}
        assigned_group: dict[str, str] = {}
        assigned_row: dict[str, RegionTag] = {}
        slot_rows: dict[str, list[RegionTag]] = {s: [] for s in DISPLAY_SLOTS}

        for tag, row in by_tag.items():
            slot, group = self._assign_slot_and_group(row)
            assigned_slot[tag] = slot
            assigned_group[tag] = group
            assigned_row[tag] = row
            if slot in slot_rows:
                slot_rows[slot].append(row)

        return {
            "assigned_slot_by_tag": assigned_slot,
            "assigned_group_by_tag": assigned_group,
            "assigned_row_by_tag": assigned_row,
            "slot_rows_cache": slot_rows,
        }

    # 태그 레벨 명시적 슬롯 오버라이드 (data 오배치 보정)
    # 형식: norm_text(tag) → (slot, group)
    _TAG_SLOT_OVERRIDES: dict[str, tuple[str, str]] = {
        # ── LEGS_FEET: 발가락/발톱 관련 ──────────────────────
        "toe nails":           ("LEGS_FEET", "nails"),
        "toenails":            ("LEGS_FEET", "nails"),
        "painted toenails":    ("LEGS_FEET", "nails"),
        "toe nail polish":     ("LEGS_FEET", "nails"),
        "toenail polish":      ("LEGS_FEET", "nails"),
        # ── ARMS_HANDS: 손가락/손톱 관련 ────────────────────
        "long fingernails":    ("ARMS_HANDS", "nails"),
        "fingernails":         ("ARMS_HANDS", "nails"),
        "painted nails":       ("ARMS_HANDS", "nails"),
        "nail art":            ("ARMS_HANDS", "nails"),
        "nail polish":         ("ARMS_HANDS", "nails"),
        "long nails":          ("ARMS_HANDS", "nails"),
        "sharp nails":         ("ARMS_HANDS", "nails"),
        "claw":                ("ARMS_HANDS", "nails"),
        "claws":               ("ARMS_HANDS", "nails"),
        "decorated nails":     ("ARMS_HANDS", "nails"),
        # ── STYLE: 렌더링/색감/신체 드로잉 스타일 ───────────
        "anime coloring":      ("STYLE", "fashion style"),
        "cel shading":         ("STYLE", "fashion style"),
        "lineart":             ("STYLE", "fashion style"),
        "body writing":        ("STYLE", "design modifiers"),
        "clothes writing":     ("STYLE", "design modifiers"),
        "text on clothes":     ("STYLE", "design modifiers"),
        "tattoo":              ("STYLE", "design modifiers"),
        "body tattoo":         ("STYLE", "design modifiers"),
        "brand name":          ("STYLE", "design modifiers"),
        "logo":                ("STYLE", "design modifiers"),
        "skin tight":          ("STYLE", "silhouette & exposure"),
        "painted body":        ("STYLE", "design modifiers"),
    }

    def _assign_slot_and_group(self, row: RegionTag) -> tuple[str, str]:
        t = norm_text(row.tag)

        # 0. 태그 레벨 명시적 오버라이드 (최우선)
        if t in self._TAG_SLOT_OVERRIDES:
            return self._TAG_SLOT_OVERRIDES[t]

        group = self._display_subgroup(row)
        g = norm_text(group)

        if self._is_style_non_garment(row, group):
            return "STYLE", self._map_style_subgroup(row.tag, row.subgroup)

        # 그룹 기반 슬롯 오버라이드 (리전 오배치 방지)
        if g in {"shirt", "tops", "outerwear", "knitwear", "sleeves", "swimsuit", "bikini", "bra", "suits & formal"}:
            return "UPPER_BODY", group
        if g in {"bottoms", "panties", "waist accessories", "aprons"}:
            return "WAIST_HIP", group
        if g in {"legwear", "footwear", "leg accessories"}:
            return "LEGS_FEET", group
        if g in {"wrist accessories", "arm accessories", "gloves", "handwear", "nails", "rings"}:
            return "ARMS_HANDS", group
        if g in {"headwear", "hair accessories", "eyewear", "mask", "masks", "neckwear", "earrings & piercings"}:
            return "HEAD_NECK_FACE", group

        # 어휘 기반 보정 (collar/shirt 계열)
        if any(k in t for k in ("shirt", "blouse", "t-shirt", "top", "camisole", "cardigan", "jacket", "coat", "hoodie", "sweater", "bra")):
            return "UPPER_BODY", group

        # 어휘 기반 보정 (손발톱/발 관련 폴백)
        if any(k in t for k in ("toe nail", "toenail")):
            return "LEGS_FEET", "nails"
        if any(k in t for k in ("fingernail", "finger nail")):
            return "ARMS_HANDS", "nails"

        region = self._effective_region(row)
        if region in {"LEGS", "FEET"}:
            return "LEGS_FEET", group
        if region in {"HEAD_NECK_FACE", "UPPER_BODY", "WAIST_HIP", "ARMS_HANDS"}:
            return region, group
        return "STYLE", group

    def _effective_region(self, row: RegionTag | None) -> str:
        if row is None:
            return ""
        tag = norm_text(row.tag)
        if "swimsuit" in tag or "bikini" in tag:
            return "UPPER_BODY"
        return str(row.region or "")

    def _display_subgroup(self, row: RegionTag | None) -> str:
        if row is None:
            return "other"
        tag = norm_text(row.tag)
        subgroup = norm_text(row.subgroup)
        if subgroup == "arrite":
            subgroup = "attire"

        if "bikini" in tag:
            return "bikini"
        if "swimsuit" in tag:
            return "swimsuit"
        if "shirt" in tag:
            return "shirt"
        if subgroup == "attire":
            return self._map_attire_subgroup(tag)
        if subgroup == "accessories":
            return self._map_accessory_subgroup(tag)
        if subgroup in {"design elements", "covering", "states", "tan marks", "patterns", "prints"}:
            return self._map_style_subgroup(tag, subgroup)
        if not subgroup:
            attire_guess = self._map_attire_subgroup(tag)
            if attire_guess != "attire":
                return attire_guess
            acc_guess = self._map_accessory_subgroup(tag)
            if acc_guess != "decorative accessories":
                return acc_guess
        return subgroup if subgroup else "other"

    def _is_style_non_garment(self, row: RegionTag | None, display_group: str) -> bool:
        if row is None:
            return False
        raw = norm_text(row.subgroup)
        tag = norm_text(row.tag)
        if raw in {"fashion style", "design elements", "covering", "states", "tan marks", "patterns", "prints"}:
            return True
        if display_group in {
            "fashion style", "design modifiers", "patterns & prints",
            "cutout & openings", "open/closure states", "damage & condition",
            "silhouette & exposure", "fit & drape", "tan & marks",
        }:
            return True
        if any(k in tag for k in (
            "cutout", "open clothes", "under clothes", "see-through",
            "highleg", "off-shoulder", "strapless", "wet clothes", "torn clothes",
        )):
            return True
        # 렌더링/색감/신체 그래픽 스타일 — 의류 아님
        if any(k in tag for k in (
            "coloring", "shading", "lineart", "cel shading",
            "body writing", "clothes writing", "text on clothes",
            "tattoo", "painted body", "brand name", " logo",
        )):
            return True
        return False

    def _map_style_subgroup(self, tag: str, raw_subgroup: str) -> str:
        t = norm_text(tag)
        s = norm_text(raw_subgroup)
        if s == "fashion style":
            return "fashion style"
        if any(k in t for k in ("cutout", "opening", "slit", "window")):
            return "cutout & openings"
        if any(k in t for k in ("open ", "opened", "unbuttoned", "unzipped", "partially open", "under clothes", "underwear only")):
            return "open/closure states"
        if any(k in t for k in ("torn", "ripped", "wet", "dirty", "stained", "blood on")):
            return "damage & condition"
        if any(k in t for k in ("highleg", "strapless", "off-shoulder", "backless", "sideboob", "underboob", "cleavage", "no bra", "no panties")):
            return "silhouette & exposure"
        if any(k in t for k in ("tight", "taut", "loose", "oversized", "undersized", "baggy")):
            return "fit & drape"
        if s in {"patterns", "prints"} or any(k in t for k in ("striped", "plaid", "checkered", "polka dot", "floral", "print")):
            return "patterns & prints"
        if s == "tan marks" or "tanline" in t:
            return "tan & marks"
        return "design modifiers"

    def _map_attire_subgroup(self, tag: str) -> str:
        t = norm_text(tag)
        if any(k in t for k in ("uniform", "serafuku", "seifuku", "gym clothes", "school swimsuit")):
            return "uniforms"
        if any(k in t for k in ("kimono", "yukata", "hanfu", "hakama", "miko", "japanese clothes", "chinese clothes")):
            return "traditional wear"
        if any(k in t for k in ("dress", "gown")):
            return "dresses"
        if any(k in t for k in ("bodysuit", "leotard", "jumpsuit", "catsuit", "unitard", "overalls", "onesie")):
            return "full-body outfits"
        if any(k in t for k in ("jacket", "coat", "hoodie", "cloak", "cape", "shawl", "cardigan", "blazer", "haori", "bolero", "poncho", "parka", "robe")):
            return "outerwear"
        if any(k in t for k in ("sweater", "pullover", "turtleneck", "knit")):
            return "knitwear"
        if any(k in t for k in ("blouse", "camisole", "tank top", "crop top", "tube top", "t-shirt", "top")):
            return "tops"
        if any(k in t for k in ("skirt", "pants", "shorts", "jeans", "trousers")):
            return "bottoms"
        if any(k in t for k in ("costume", "cosplay", "maid", "nurse", "idol", "playboy bunny", "magical girl")):
            return "costumes & themes"
        if any(k in t for k in ("suit", "tuxedo", "blazer set", "business wear", "office wear")):
            return "suits & formal"
        if any(k in t for k in ("lingerie", "negligee", "bodystocking", "harness", "underwear", "panties")):
            return "intimate"
        if any(k in t for k in ("open ", "torn ", "wet ", "see-through", "strapless", "off-shoulder", "highleg", "cutout", "under clothes", "underwear only")):
            return "clothing states"
        if any(k in t for k in ("outfit", "clothes", "wear", "costume set", "set")):
            return "named outfits"
        return "named outfits"

    def _map_accessory_subgroup(self, tag: str) -> str:
        t = norm_text(tag)
        if any(k in t for k in ("hair ", "hairband", "hairclip", "scrunchie", "hair ornament", "hair flower")):
            return "hair accessories"
        if any(k in t for k in ("earring", "piercing", "nose ring")):
            return "earrings & piercings"
        if any(k in t for k in ("choker", "neck", "collar", "necktie", "bowtie", "scarf", "ascot", "necklace", "pendant")):
            return "neckwear"
        if any(k in t for k in ("wrist", "bracelet", "bangle", "watch", "cuff")):
            return "wrist accessories"
        if any(k in t for k in ("armband", "armlet", "arm strap", "arm guard")):
            return "arm accessories"
        if any(k in t for k in ("belt", "sash", "obi", "suspenders")):
            return "waist accessories"
        if any(k in t for k in ("anklet", "thigh strap", "garter strap", "leg ribbon", "thighlet")):
            return "leg accessories"
        if any(k in t for k in ("bag", "backpack", "handbag", "pouch", "satchel", "briefcase")):
            return "bags"
        if any(k in t for k in ("nails", "nail polish", "nail")):
            return "nails"
        if any(k in t for k in ("bow", "ribbon")):
            return "bows & ribbons"
        if any(k in t for k in ("pin", "badge", "brooch", "emblem", "insignia")):
            return "pins & badges"
        if any(k in t for k in ("chain", "charm", "amulet", "medal", "pendant")):
            return "charms & chains"
        if any(k in t for k in ("bead", "pearl", "crystal", "gem", "jewel")):
            return "gems & beads"
        if any(k in t for k in ("strap", "cord", "string", "rope", "band")):
            return "straps & cords"
        if any(k in t for k in ("flower", "rose", "lily", "petal", "floral")):
            return "floral accessories"
        if any(k in t for k in ("ornament", "decoration", "accessory")):
            return "ornaments"
        if "jewelry" in t:
            return "jewelry"
        return "misc accessories"


# ---------------------------------------------------------------------------
# RulesEngine — 추천/회피/페어/충돌 규칙
# ---------------------------------------------------------------------------

class RulesEngine:
    """staged_tags 기반으로 추천/회피/페어 집계 + 충돌 검출.

    소스: viewer_clothes.py L886-892 (pair_edge_pass), L1150-1195 (issue_map),
          L1219-1261 (refresh_rules)
    """

    @staticmethod
    def pair_edge_pass(row: dict[str, Any], pair_mode: str) -> bool:
        """Pair 모드 프로필에 따라 edge 필터링."""
        prof = PAIR_MODE_PROFILES.get(pair_mode, PAIR_MODE_PROFILES["Balanced"])
        return (
            float(row.get("confidence", 0.0)) >= float(prof["pair_min_conf"])
            and int(row.get("pair_post_count", 0)) >= int(prof["pair_min_count"])
            and float(row.get("lift", 0.0)) >= float(prof["pair_min_lift"])
        )

    @staticmethod
    def refresh_rules(
        staged_tags: list[str],
        reco_by_seed: dict[str, list[dict[str, Any]]],
        avoid_by_seed: dict[str, list[dict[str, Any]]],
        pair_by_seed: dict[str, list[dict[str, Any]]],
        pair_mode: str,
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
    ]:
        """staged_tags에 대한 reco/avoid/pair 집계 반환."""
        seeds = set(staged_tags)

        # 추천 집계
        reco_agg: dict[str, dict[str, Any]] = {}
        for s in staged_tags:
            for r in reco_by_seed.get(s, []):
                t = r["tag"]
                if not t or t in seeds:
                    continue
                a = reco_agg.setdefault(t, {"score": 0.0, "max_conf": 0.0, "hits": 0})
                a["score"] += float(r["score"])
                a["max_conf"] = max(float(a["max_conf"]), float(r["conf"]))
                a["hits"] += 1

        # 회피 집계
        avoid_agg: dict[str, dict[str, Any]] = {}
        for s in staged_tags:
            for r in avoid_by_seed.get(s, []):
                t = r["tag"]
                if not t or t in seeds:
                    continue
                a = avoid_agg.setdefault(t, {"score": 0.0, "min_lift": 999.0, "hits": 0})
                a["score"] += float(r["score"])
                a["min_lift"] = min(float(a["min_lift"]), float(r["lift"]))
                a["hits"] += 1

        # 페어 집계
        pair_agg: dict[str, dict[str, Any]] = {}
        for s in staged_tags:
            for r in pair_by_seed.get(s, []):
                if not RulesEngine.pair_edge_pass(r, pair_mode):
                    continue
                t = r["tag"]
                if not t or t in seeds:
                    continue
                a = pair_agg.setdefault(t, {"conf_sum": 0.0, "max_conf": 0.0, "hits": 0, "max_pair": 0})
                conf = float(r["confidence"])
                a["conf_sum"] += conf
                a["max_conf"] = max(float(a["max_conf"]), conf)
                a["hits"] += 1
                a["max_pair"] = max(int(a["max_pair"]), int(r["pair_post_count"]))

        return reco_agg, avoid_agg, pair_agg

    @staticmethod
    def compute_staging_issue_map(
        staged_tags: list[str],
        avoid_by_seed: dict[str, list[dict[str, Any]]],
        conflict_pairs: set[tuple[str, str]],
        conflict_exclusion_score: dict[tuple[str, str], float],
    ) -> dict[str, list[str]]:
        """staged_tags 간 충돌/경고 이슈 맵 반환."""
        staged = [t for t in staged_tags if t]
        staged_set = set(staged)

        pair_metrics: dict[tuple[str, str], dict[str, float]] = {}
        for a in staged:
            for r in avoid_by_seed.get(a, []):
                b = str(r.get("tag") or "")
                if not b or b == a or b not in staged_set:
                    continue
                key = tuple(sorted((a, b)))
                m = pair_metrics.setdefault(
                    key,
                    {"min_lift": 999.0, "max_avoid_score": 0.0, "max_pair_count": 0.0, "max_conf": 0.0},
                )
                m["min_lift"] = min(float(m["min_lift"]), float(r.get("lift", 999.0)))
                m["max_avoid_score"] = max(float(m["max_avoid_score"]), float(r.get("score", 0.0)))
                m["max_pair_count"] = max(float(m["max_pair_count"]), float(r.get("pair_post_count", 0.0)))
                m["max_conf"] = max(float(m["max_conf"]), float(r.get("confidence", 0.0)))

        issue_sets: dict[str, set[str]] = defaultdict(set)
        for (a, b), m in pair_metrics.items():
            if float(m["min_lift"]) > float(LOW_LIFT_ALERT_LIFT_MAX):
                continue
            if float(m["max_pair_count"]) >= float(LOW_LIFT_IGNORE_PAIRCOUNT_MIN):
                continue
            if float(m["max_conf"]) >= float(LOW_LIFT_CARE_CONF_MAX):
                continue
            reason = f"low-lift({float(m['min_lift']):.3f})"
            issue_sets[a].add(reason)
            issue_sets[b].add(reason)

        n = len(staged)
        for i in range(n):
            a = staged[i]
            for j in range(i + 1, n):
                b = staged[j]
                key = tuple(sorted((a, b)))
                if key in conflict_pairs:
                    ex = float(conflict_exclusion_score.get(key, 0.0))
                    reason = f"hard-conflict({ex:.3f})"
                    issue_sets[a].add(reason)
                    issue_sets[b].add(reason)

        return {k: sorted(v) for k, v in issue_sets.items()}


# ---------------------------------------------------------------------------
# ExpressionEngine — 표현 콤보 집계
# ---------------------------------------------------------------------------

class ExpressionEngine:
    """staged_tags에 기반한 예상 표현 집계.

    소스: viewer_clothes.py L1030-1068
    """

    @staticmethod
    def aggregate_for_staged(
        staged: list[str],
        expr_by_combo: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """staged tags를 모두 포함하는 콤보의 표현을 합산."""
        if not staged:
            return []
        staged_set = set(staged)
        agg: dict[str, dict[str, Any]] = {}
        for combo, rows in expr_by_combo.items():
            combo_tags = set(parse_csv_tags(combo))
            if not staged_set.issubset(combo_tags):
                continue
            for r in rows:
                expr = str(r["expression_combo"])
                prev = agg.get(expr)
                w = int(r["count"]) if int(r["count"]) > 0 else 1
                if prev is None:
                    agg[expr] = {
                        "expression_combo": expr,
                        "count": int(r["count"]),
                        "confidence_sum": float(r["confidence"]) * w,
                        "weight": w,
                        "expr_tags": int(r["expr_tags"]),
                    }
                else:
                    prev["count"] += int(r["count"])
                    prev["confidence_sum"] += float(r["confidence"]) * w
                    prev["weight"] += w

        out: list[dict[str, Any]] = []
        for expr, r in agg.items():
            weight = int(r["weight"]) if int(r["weight"]) > 0 else 1
            out.append({
                "expression_combo": expr,
                "count": int(r["count"]),
                "confidence": float(r["confidence_sum"]) / weight,
                "expr_tags": int(r["expr_tags"]),
            })
        out.sort(key=_expression_sort_key)
        return out


# ---------------------------------------------------------------------------
# PromptBuilder — 프롬프트 텍스트 빌드
# ---------------------------------------------------------------------------

class PromptBuilder:
    """staged_tags → 프롬프트 텍스트 조립.

    소스: viewer_clothes.py L1197-1204
    """

    @staticmethod
    def build(staged_tags: list[str], current_combo: str = "",
              rating_tags: list[str] | None = None) -> str:
        """'1girl, rating_tags..., tag1, tag2, ...' 형태의 프롬프트 빌드.

        rating_tags가 주어지면 '1girl' 바로 뒤(인덱스 1)에 삽입한다.
        """
        tags: list[str] = ["1girl"]
        if rating_tags:
            tags.extend(rating_tags)
        tags.extend([t for t in staged_tags if t])
        if len(tags) <= 1 and current_combo:
            tags.extend(parse_csv_tags(current_combo))
        tags = unique_preserve(tags)
        return ", ".join(tags)


# ---------------------------------------------------------------------------
# 모듈 레벨 유틸리티
# ---------------------------------------------------------------------------

def _expression_sort_key(row: dict[str, Any]) -> tuple[int, float, int, str]:
    """표현 정렬 키: 단일 태그 → 하위, 신뢰도 높은 순."""
    single_bottom = 1 if int(row.get("expr_tags", 0)) <= 1 else 0
    return (
        single_bottom,
        -float(row.get("confidence", 0.0)),
        -int(row.get("count", 0)),
        str(row.get("expression_combo", "")),
    )


def compute_promoted_tags(
    region_staged: dict[str, list[str]],
    assigned_row_by_tag: dict[str, RegionTag],
    assigned_group_by_tag: dict[str, str],
    slot_top_pct: float = 0.25,
    subgroup_top_pct: float = 0.50,
) -> set[str]:
    """region_staged에서 promoted(메인 스테이지) 태그 집합을 계산.

    기준 (OR 조건 — 어느 하나라도 만족하면 promoted):
    1. 슬롯 내 post_count 상위 ceil(N * slot_top_pct) 태그
    2. 서브그룹 내 post_count 상위 ceil(N * subgroup_top_pct) 태그
    """
    promoted: set[str] = set()

    def _pc(tag: str) -> int:
        row = assigned_row_by_tag.get(tag)
        return int(row.post_count) if row is not None else 0

    # 기준 1: 슬롯별 상위 20%
    for slot, tags in region_staged.items():
        if not tags:
            continue
        sorted_tags = sorted(tags, key=_pc, reverse=True)
        top_n = ceil(len(sorted_tags) * slot_top_pct)
        for tag in sorted_tags[:top_n]:
            promoted.add(tag)

    # 기준 2: 서브그룹별 상위 40%
    by_subgroup: dict[str, list[str]] = defaultdict(list)
    for tags in region_staged.values():
        for tag in tags:
            sg = assigned_group_by_tag.get(tag, "other")
            by_subgroup[sg].append(tag)

    for sg, tags in by_subgroup.items():
        if not tags:
            continue
        sorted_tags = sorted(tags, key=_pc, reverse=True)
        top_n = ceil(len(sorted_tags) * subgroup_top_pct)
        for tag in sorted_tags[:top_n]:
            promoted.add(tag)

    return promoted


# ---------------------------------------------------------------------------
# Expression 그룹 분류
# ---------------------------------------------------------------------------

_EXPR_MODIFIERS: set[str] = {
    "blush", "light blush", "blush stickers", "nose blush",
    "open mouth", "closed mouth",
    "closed eyes", "one eye closed", "half-closed eyes",
    "raised eyebrows",
}

# (그룹명, 표시 라벨, 앵커 태그)  — 우선순위 순서
EXPRESSION_GROUPS: list[tuple[str, str, set[str]]] = [
    ("tears",      "tears (슬픔)",
     {"tears", "crying", "crying with eyes open", "tearing up"}),
    ("angry",      "angry (화남)",
     {"angry", "frown", "light frown", "annoyed", "defeat"}),
    ("shy",        "shy (수줍음)",
     {"embarrassed", "shy", "nervous", "sweatdrop"}),
    ("emoticon",   "emoticon (이모티콘)",
     {":d", ":3", ":p", ":q", ";d", ";)", ";p", ":>", "^^^", ";o"}),
    ("surprise",   "surprise (놀람)",
     {":o", ";o", "surprised"}),
    ("displeased", "displeased (불만)",
     {":<", ":/"}),
    ("grin",       "grin (씩웃음)",
     {"grin", "smirk", "smug", "evil smile", "evil grin", "seductive smile"}),
    ("smile",      "smile (미소)",
     {"smile", "light smile", "happy"}),
    ("stoic",      "stoic (무표정)",
     {"expressionless", "serious", "sleepy", "wavy mouth",
      "dot mouth", "sideways mouth"}),
    ("physical",   "physical (신체반응)",
     {"blood on face", "blood from mouth", "nosebleed", "snot",
      "saliva", "heavy breathing", "drunk"}),
    ("special",    "special (특수)",
     {"facepaint", "reverse trap", "food on face", "averting eyes"}),
]


def classify_expression_combo(expr_combo: str) -> str:
    """표정 combo → 그룹 key 반환."""
    tags = {t.strip() for t in expr_combo.split(",") if t.strip()}
    core = tags - _EXPR_MODIFIERS
    if not core:
        return "base"
    for group_key, _label, anchors in EXPRESSION_GROUPS:
        if core & anchors:
            return group_key
    return "other"


def build_expression_group_tree(
    expr_global: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """expr_global 리스트를 그룹별로 분류하여 반환.

    Returns: {group_key: [row, ...]}  — 각 row 는 expr_global 의 원본 dict.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in expr_global:
        combo = str(row.get("expression_combo", ""))
        key = classify_expression_combo(combo)
        grouped.setdefault(key, []).append(row)
    # count 내림차순 정렬
    for rows in grouped.values():
        rows.sort(key=lambda r: -int(r.get("count", 0)))
    return grouped
