"""
Clothes Preset Data Manager — ZIP I/O + 캐시 관리

naia_clothes_preset ZIP 아카이브에서 parquet 데이터를 읽고,
pickle 캐시로 반복 로딩을 최적화한다.

패턴 참조: ui/event_preset/data_manager.py
소스 참조: viewer_clothes.py L88-869
"""
from __future__ import annotations

import hashlib
import io
import pickle
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

PACKAGE_FILE_NAME = "naia_clothes_preset"
CACHE_FILE_NAME = "viewer_clothes_cache_step34.pkl"
CACHE_VERSION = 1

REQUIRED_DATA_FILES = [
    "expression_combo_by_clothing_gsq_1girl_solo.parquet",
    "clothing_combo_index_gsq_1girl_solo.parquet",
    "clothing_region6_mapping_step42.parquet",
    "clothing_recommendation_rules_gsq_1girl_solo.parquet",
    "clothing_discouraged_rules_gsq_1girl_solo.parquet",
    "clothing_pair_cooccurrence_gsq_1girl_solo.parquet",
    "clothing_conflict_rules_gsq_1girl_solo.parquet",
]

REGIONS = [
    "HEAD_NECK_FACE", "UPPER_BODY", "WAIST_HIP",
    "ARMS_HANDS", "LEGS", "FEET",
]


# ---------------------------------------------------------------------------
# 유틸리티 함수
# ---------------------------------------------------------------------------

def norm_text(value: Any) -> str:
    """태그 정규화: lower + underscore→space + 연속 공백 제거."""
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def parse_csv_tags(value: Any) -> list[str]:
    """콤마 구분 태그 문자열 → 정규화된 태그 리스트."""
    if not isinstance(value, str) or not value.strip():
        return []
    return [norm_text(v) for v in value.split(",") if norm_text(v)]


def unique_preserve(values: list[str]) -> list[str]:
    """순서 보존 중복 제거."""
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def fmt_k_count(value: int) -> str:
    """숫자 → '1.2k', '150' 등 간략 표시."""
    n = int(value or 0)
    if n < 1000:
        return str(n)
    k = n / 1000.0
    if k >= 100:
        return f"{k:,.0f}k"
    return f"{k:,.1f}k"


# ---------------------------------------------------------------------------
# 데이터클래스
# ---------------------------------------------------------------------------

@dataclass
class ComboSummary:
    """의류 콤보 요약 (콤보 테이블 행)."""
    clothing_combo: str
    post_count: int
    tag_count: int
    tags: tuple[str, ...]


@dataclass
class RegionTag:
    """리전 매핑 태그 (6-슬롯 트리 행)."""
    tag: str
    region: str
    subgroup: str
    post_count: int
    confidence: float
    reason: str


# ---------------------------------------------------------------------------
# 캐시 언피클러
# ---------------------------------------------------------------------------

class _CacheUnpickler(pickle.Unpickler):
    """ComboSummary / RegionTag 역직렬화를 위한 커스텀 언피클러."""
    def find_class(self, module: str, name: str):
        if name == "ComboSummary":
            return ComboSummary
        if name == "RegionTag":
            return RegionTag
        return super().find_class(module, name)


# ---------------------------------------------------------------------------
# 메인 데이터 매니저
# ---------------------------------------------------------------------------

class ClothesPresetDataManager:
    """naia_clothes_preset ZIP 아카이브 관리자.

    viewer_clothes.py의 ZIP I/O + 캐시 + 데이터 로딩을 분리하여 캡슐화.
    load_all()이 반환하는 dict를 윈도우/엔진에서 사용한다.
    """

    def __init__(self, data_dir: Path | None = None):
        if data_dir is None:
            data_dir = Path(__file__).resolve().parent
        self._data_dir = data_dir
        self._package_path = data_dir / PACKAGE_FILE_NAME
        self._cache_path = data_dir / CACHE_FILE_NAME
        self._zip_ref: zipfile.ZipFile | None = None
        self._zip_name_map: dict[str, str] = {}

        # 파일 경로
        self._combo_path = data_dir / "expression_combo_by_clothing_gsq_1girl_solo.parquet"
        self._combo_index_path = data_dir / "clothing_combo_index_gsq_1girl_solo.parquet"
        self._region_map_path = data_dir / "clothing_region6_mapping_step42.parquet"
        self._reco_path = data_dir / "clothing_recommendation_rules_gsq_1girl_solo.parquet"
        self._avoid_path = data_dir / "clothing_discouraged_rules_gsq_1girl_solo.parquet"
        self._pair_path = data_dir / "clothing_pair_cooccurrence_gsq_1girl_solo.parquet"
        self._conflict_path = data_dir / "clothing_conflict_rules_gsq_1girl_solo.parquet"

    # ----- public API -----

    def is_data_available(self) -> bool:
        """ZIP 존재 + 최소 유효성 확인."""
        if not self._package_path.exists():
            return False
        try:
            zf = self._open_zip()
            return any(
                f.endswith(".parquet") for f in zf.namelist()
            )
        except (zipfile.BadZipFile, Exception):
            return False

    def load_all(self) -> dict[str, Any]:
        """전체 데이터를 로딩하여 dict payload로 반환.

        캐시가 있으면 캐시에서 복원, 없으면 parquet에서 cold-build.
        """
        payload = self._try_load_cache()
        if payload is not None:
            return payload

        payload = self._cold_build()

        # 캐시 저장
        self._save_cache(payload)
        return payload

    def close(self) -> None:
        """ZIP 참조 정리."""
        if self._zip_ref is not None:
            try:
                self._zip_ref.close()
            except Exception:
                pass
            self._zip_ref = None
            self._zip_name_map = {}

    # ----- ZIP I/O -----

    def _open_zip(self) -> zipfile.ZipFile:
        if self._zip_ref is not None:
            return self._zip_ref
        self._zip_ref = zipfile.ZipFile(self._package_path, "r")
        name_map: dict[str, str] = {}
        for zname in self._zip_ref.namelist():
            if zname.endswith("/"):
                continue
            bname = Path(zname).name
            if bname and bname not in name_map:
                name_map[bname] = zname
        self._zip_name_map = name_map
        return self._zip_ref

    def _ensure_zip_index(self) -> None:
        if self._zip_ref is not None:
            return
        if not self._package_path.exists() or not zipfile.is_zipfile(self._package_path):
            return
        try:
            self._open_zip()
        except Exception:
            self._zip_ref = None
            self._zip_name_map = {}

    def _resource_exists(self, path: Path) -> bool:
        if path.exists():
            return True
        self._ensure_zip_index()
        return path.name in self._zip_name_map

    def _read_table(self, path: Path):
        if path.exists():
            return pq.read_table(path)
        self._ensure_zip_index()
        zname = self._zip_name_map.get(path.name, "")
        if not zname or self._zip_ref is None:
            raise FileNotFoundError(str(path))
        with self._zip_ref.open(zname, "r") as src:
            data = src.read()
        return pq.read_table(pa.BufferReader(data))

    # ----- 캐시 -----

    def _cache_sources(self) -> list[Path]:
        if self._package_path.exists() and not self._combo_index_path.exists():
            return [self._package_path]
        return [
            self._combo_index_path, self._combo_path, self._region_map_path,
            self._reco_path, self._avoid_path, self._pair_path, self._conflict_path,
        ]

    def _cache_key(self) -> str:
        parts: list[str] = [f"cache_version={CACHE_VERSION}"]
        for path in self._cache_sources():
            if not path.exists():
                parts.append(f"{path.name}|missing")
                continue
            st = path.stat()
            parts.append(f"{path.name}|{st.st_size}|{st.st_mtime_ns}")
        raw = "\n".join(parts).encode("utf-8", errors="ignore")
        return hashlib.sha256(raw).hexdigest()

    def _loads_payload(self, raw: bytes) -> dict[str, Any] | None:
        try:
            return pickle.loads(raw)
        except Exception:
            try:
                return _CacheUnpickler(io.BytesIO(raw)).load()
            except Exception:
                return None

    def _try_load_cache(self) -> dict[str, Any] | None:
        payload: dict[str, Any] | None = None
        from_zip = False

        # 1) 로컬 캐시
        if self._cache_path.exists():
            try:
                with self._cache_path.open("rb") as f:
                    payload = self._loads_payload(f.read())
            except Exception:
                payload = None

        # 2) ZIP 내장 캐시
        if payload is None:
            self._ensure_zip_index()
            zname = self._zip_name_map.get(CACHE_FILE_NAME, "")
            if zname and self._zip_ref is not None:
                try:
                    with self._zip_ref.open(zname, "r") as src:
                        payload = self._loads_payload(src.read())
                        from_zip = payload is not None
                except Exception:
                    payload = None

        if payload is None or not isinstance(payload, dict):
            return None
        if int(payload.get("cache_version", -1)) != CACHE_VERSION:
            return None
        if (not from_zip) and str(payload.get("cache_key", "")) != self._cache_key():
            return None

        # 필수 키 검증
        required_keys = [
            "combo_summaries", "combo_summaries_ge2", "combo_tag_to_ids",
            "region_tags", "region_to_tags", "region_summary", "tag_to_region",
            "reco_by_seed", "avoid_by_seed", "pair_by_seed",
            "conflict_pairs", "conflict_exclusion_score",
            "expr_by_combo", "expr_global",
            "assigned_slot_by_tag", "assigned_group_by_tag",
            "assigned_row_by_tag", "slot_rows_cache",
        ]
        if not all(k in payload for k in required_keys):
            return None

        payload["cache_status"] = "hit"
        return payload

    def _save_cache(self, payload: dict[str, Any]) -> None:
        save_payload = dict(payload)
        save_payload["cache_version"] = CACHE_VERSION
        save_payload["cache_key"] = self._cache_key()
        try:
            with self._cache_path.open("wb") as f:
                pickle.dump(save_payload, f, protocol=pickle.HIGHEST_PROTOCOL)
            payload["cache_status"] = "miss(rebuilt)"
        except Exception:
            payload["cache_status"] = "miss(cache-write-failed)"

    # ----- Cold Build -----

    def _cold_build(self) -> dict[str, Any]:
        """parquet 파일들에서 전체 데이터를 cold-build."""
        payload: dict[str, Any] = {"cache_status": "cold"}

        # 콤보 카탈로그
        self._load_combo_catalog(payload)

        # 표현 카탈로그
        self._load_expression_catalog(payload)

        # 리전 매핑
        self._load_region_mapping(payload)

        # 규칙 (추천/회피/페어/충돌)
        self._load_rules(payload)

        # 슬롯 할당은 엔진에서 수행 (TaxonomyEngine.rebuild_slot_assignment)
        # 여기서는 빈 자리 표시자
        payload["assigned_slot_by_tag"] = {}
        payload["assigned_group_by_tag"] = {}
        payload["assigned_row_by_tag"] = {}
        payload["slot_rows_cache"] = {}

        return payload

    def _ingest_combo_rows(self, rows: list[dict[str, Any]]) -> tuple[
        list[ComboSummary], list[ComboSummary], dict[str, set[int]]
    ]:
        combos: list[ComboSummary] = []
        tag_to_ids: dict[str, set[int]] = defaultdict(set)
        for row in rows:
            combo = norm_text(row.get("clothing_combo"))
            if not combo:
                continue
            tags = tuple(sorted(set(parse_csv_tags(combo))))
            if not tags:
                continue
            post_count = int(row.get("post_count") or 0)
            tag_count = int(row.get("tag_count") or len(tags))
            combos.append(ComboSummary(combo, post_count, tag_count, tags))
        combos.sort(key=lambda x: (-x.post_count, x.tag_count, x.clothing_combo))
        for i, c in enumerate(combos):
            for t in c.tags:
                tag_to_ids[t].add(i)
        ge2 = [c for c in combos if c.tag_count >= 2]
        return combos, ge2, tag_to_ids

    def _load_combo_catalog(self, payload: dict[str, Any]) -> None:
        if self._resource_exists(self._combo_index_path):
            rows = self._read_table(self._combo_index_path).to_pylist()
            all_combos, ge2, tag_to_ids = self._ingest_combo_rows(rows)
            payload["combo_summaries"] = all_combos
            payload["combo_summaries_ge2"] = ge2
            payload["combo_tag_to_ids"] = tag_to_ids
            return

        if not self._resource_exists(self._combo_path):
            payload["combo_summaries"] = []
            payload["combo_summaries_ge2"] = []
            payload["combo_tag_to_ids"] = {}
            return

        # Fallback: expression-combo aggregate
        combo_tbl = self._read_table(self._combo_path).to_pydict()
        by_combo: dict[str, int] = defaultdict(int)
        for combo, cnt in zip(combo_tbl["clothing_combo"], combo_tbl["post_count"]):
            by_combo[norm_text(combo)] += int(cnt or 0)
        rows = []
        for combo, total in by_combo.items():
            tags = sorted(set(parse_csv_tags(combo)))
            rows.append({"clothing_combo": combo, "post_count": int(total), "tag_count": len(tags)})
        all_combos, ge2, tag_to_ids = self._ingest_combo_rows(rows)
        payload["combo_summaries"] = all_combos
        payload["combo_summaries_ge2"] = ge2
        payload["combo_tag_to_ids"] = tag_to_ids

    def _load_expression_catalog(self, payload: dict[str, Any]) -> None:
        expr_by_combo: dict[str, list[dict[str, Any]]] = {}
        expr_global: list[dict[str, Any]] = []

        if not self._resource_exists(self._combo_path):
            payload["expr_by_combo"] = expr_by_combo
            payload["expr_global"] = expr_global
            return

        t = self._read_table(self._combo_path).to_pydict()
        global_map: dict[str, dict[str, Any]] = {}
        for i in range(len(t["clothing_combo"])):
            combo = norm_text(t["clothing_combo"][i])
            expr = norm_text(t["expression_combo"][i])
            if not combo or not expr:
                continue
            row = {
                "expression_combo": expr,
                "count": int(t["post_count"][i] or 0),
                "confidence": float(t["confidence"][i] or 0.0),
                "expr_tags": int(t["expression_tag_count"][i] or len(parse_csv_tags(expr))),
            }
            expr_by_combo.setdefault(combo, []).append(row)

            agg = global_map.get(expr)
            if agg is None:
                global_map[expr] = {
                    "expression_combo": expr,
                    "count": row["count"],
                    "confidence_sum": row["confidence"] * row["count"],
                    "weight": max(row["count"], 1),
                }
            else:
                agg["count"] += row["count"]
                agg["confidence_sum"] += row["confidence"] * row["count"]
                agg["weight"] += max(row["count"], 1)

        sort_key = self._expression_sort_key
        for combo_key in expr_by_combo:
            expr_by_combo[combo_key].sort(key=sort_key)

        for expr, agg in global_map.items():
            weight = int(agg.get("weight", 1)) or 1
            expr_global.append({
                "expression_combo": expr,
                "count": int(agg["count"]),
                "confidence": float(agg["confidence_sum"]) / weight,
                "expr_tags": len(parse_csv_tags(expr)),
            })
        expr_global.sort(key=sort_key)

        payload["expr_by_combo"] = expr_by_combo
        payload["expr_global"] = expr_global

    def _load_region_mapping(self, payload: dict[str, Any]) -> None:
        region_tags: list[RegionTag] = []
        region_to_tags: dict[str, list[RegionTag]] = {r: [] for r in REGIONS}
        region_summary: dict[str, tuple[int, int]] = {r: (0, 0) for r in REGIONS}
        tag_to_region: dict[str, str] = {}

        if self._resource_exists(self._region_map_path):
            t = self._read_table(self._region_map_path).to_pydict()
            support_sum: defaultdict[str, int] = defaultdict(int)
            for i in range(len(t["clothing_tag"])):
                row = RegionTag(
                    tag=str(t["clothing_tag"][i] or ""),
                    region=str(t["region6"][i] or ""),
                    subgroup=str(t["subgroup"][i] or ""),
                    post_count=int(t["post_count"][i] or 0),
                    confidence=float(t["mapping_confidence"][i] or 0.0),
                    reason=str(t["mapping_reason"][i] or ""),
                )
                region_tags.append(row)
                tag_to_region[row.tag] = row.region
                if row.region in region_to_tags:
                    region_to_tags[row.region].append(row)
                    support_sum[row.region] += row.post_count
            for r in REGIONS:
                tags = region_to_tags[r]
                tags.sort(key=lambda x: (-x.post_count, x.tag))
                region_summary[r] = (len(tags), int(support_sum[r]))

        payload["region_tags"] = region_tags
        payload["region_to_tags"] = region_to_tags
        payload["region_summary"] = region_summary
        payload["tag_to_region"] = tag_to_region

    def _load_rules(self, payload: dict[str, Any]) -> None:
        reco_by_seed: dict[str, list[dict[str, Any]]] = {}
        avoid_by_seed: dict[str, list[dict[str, Any]]] = {}
        pair_by_seed: dict[str, list[dict[str, Any]]] = {}
        conflict_pairs: set[tuple[str, str]] = set()
        conflict_exclusion_score: dict[tuple[str, str], float] = {}

        # 추천 규칙
        if self._resource_exists(self._reco_path):
            t = self._read_table(self._reco_path).to_pydict()
            for i in range(len(t["seed_tag"])):
                seed = str(t["seed_tag"][i] or "")
                reco_by_seed.setdefault(seed, []).append({
                    "tag": str(t["candidate_tag"][i] or ""),
                    "score": float(t["score"][i] or 0.0),
                    "conf": float(t["confidence"][i] or 0.0),
                })

        # 회피 규칙
        if self._resource_exists(self._avoid_path):
            t = self._read_table(self._avoid_path).to_pydict()
            for i in range(len(t["seed_tag"])):
                seed = str(t["seed_tag"][i] or "")
                avoid_by_seed.setdefault(seed, []).append({
                    "tag": str(t["avoid_tag"][i] or ""),
                    "score": float(t["avoid_score"][i] or 0.0),
                    "lift": float(t["lift"][i] or 0.0),
                    "pair_post_count": int(t["pair_post_count"][i] or 0),
                    "confidence": float(t["confidence"][i] or 0.0),
                })

        # 페어 공기 규칙
        if self._resource_exists(self._pair_path):
            t = self._read_table(self._pair_path).to_pydict()
            for i in range(len(t["tag_a"])):
                a = str(t["tag_a"][i] or "")
                b = str(t["tag_b"][i] or "")
                if not a or not b:
                    continue
                c_ab = float(t["confidence_a_to_b"][i] or 0.0)
                c_ba = float(t["confidence_b_to_a"][i] or 0.0)
                pair_count = int(t["pair_post_count"][i] or 0)
                lift = float(t["lift"][i] or 0.0)
                pair_by_seed.setdefault(a, []).append(
                    {"tag": b, "confidence": c_ab, "pair_post_count": pair_count, "lift": lift}
                )
                pair_by_seed.setdefault(b, []).append(
                    {"tag": a, "confidence": c_ba, "pair_post_count": pair_count, "lift": lift}
                )

        # 충돌 규칙
        if self._resource_exists(self._conflict_path):
            t = self._read_table(self._conflict_path).to_pydict()
            for i in range(len(t["tag_a"])):
                a = str(t["tag_a"][i] or "")
                b = str(t["tag_b"][i] or "")
                if not a or not b or a == b:
                    continue
                key = tuple(sorted((a, b)))
                conflict_pairs.add(key)
                conflict_exclusion_score[key] = max(
                    float(conflict_exclusion_score.get(key, 0.0)),
                    float(t["exclusion_score"][i] or 0.0),
                )

        payload["reco_by_seed"] = reco_by_seed
        payload["avoid_by_seed"] = avoid_by_seed
        payload["pair_by_seed"] = pair_by_seed
        payload["conflict_pairs"] = conflict_pairs
        payload["conflict_exclusion_score"] = conflict_exclusion_score

    @staticmethod
    def _expression_sort_key(row: dict[str, Any]) -> tuple[int, float, int, str]:
        single_bottom = 1 if int(row.get("expr_tags", 0)) <= 1 else 0
        return (
            single_bottom,
            -float(row.get("confidence", 0.0)),
            -int(row.get("count", 0)),
            str(row.get("expression_combo", "")),
        )
