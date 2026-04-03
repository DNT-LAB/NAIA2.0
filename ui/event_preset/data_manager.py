"""
Event Preset Data Manager — ZIP I/O + 에셋 로딩 + 파티션 캐시

naia_prompt_preset ZIP 아카이브에서 데이터를 읽고 캐시하는 계층.
viewer_multi.py의 open_data_zip, load_assets, _load_step15_partition_data 등을 통합.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# 데이터 파일 경로 (기본: 같은 디렉터리의 naia_prompt_preset)
# ---------------------------------------------------------------------------
DATA_ZIP_PATH = Path(__file__).resolve().parent / "naia_prompt_preset"

# ---------------------------------------------------------------------------
# 필수/선택 파일 목록
# ---------------------------------------------------------------------------
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

# 파티션 당 필요 파일 (step15)
PARTITION_FILES = [
    "event_observed_combo.parquet",
    "event_expression_cooccurrence.parquet",
    "event_clothing_cooccurrence.parquet",
    "event_characteristic_cooccurrence.parquet",
    "event_catalog.parquet",
    "quality_metrics_step15.json",
]


class EventPresetDataManager:
    """naia_prompt_preset ZIP 아카이브 관리자."""

    # 클래스 레벨 파티션 캐시: 모든 인스턴스가 공유
    # (Event Preset Window에서 로드한 파티션을 Quick Event Module에서 재사용)
    _shared_step15_cache: dict[str, dict[str, Any]] = {}

    def __init__(self, data_path: Path | None = None):
        self._data_path = data_path or DATA_ZIP_PATH
        self._zip_ref: zipfile.ZipFile | None = None
        self._step15_cache = EventPresetDataManager._shared_step15_cache
        self._available_partitions: set[str] | None = None
        self._recommendations: dict | None = None
        self._event_partition_index: dict | None = None
        self._color_prefixes: list[str] | None = None
        self._partition_row_counts: dict | None = None

    # ------------------------------------------------------------------
    # 기본 I/O
    # ------------------------------------------------------------------

    def is_data_available(self) -> bool:
        """데이터 파일 존재 + 최소 유효성 확인."""
        if not self._data_path.exists():
            return False
        try:
            zf = self._open_zip()
            return "base/tag_catalog.parquet" in zf.namelist()
        except (zipfile.BadZipFile, Exception):
            return False

    def _open_zip(self) -> zipfile.ZipFile:
        """캐시된 ZipFile 반환 (싱글턴)."""
        if self._zip_ref is None:
            self._zip_ref = zipfile.ZipFile(self._data_path, "r")
        return self._zip_ref

    def _read_parquet(self, name: str) -> pd.DataFrame:
        zf = self._open_zip()
        return pd.read_parquet(io.BytesIO(zf.read(name)))

    def _read_json(self, name: str) -> Any:
        zf = self._open_zip()
        return json.loads(zf.read(name).decode("utf-8"))

    def _read_text(self, name: str) -> str:
        zf = self._open_zip()
        return zf.read(name).decode("utf-8")

    def _exists(self, name: str) -> bool:
        zf = self._open_zip()
        return name in zf.NameToInfo

    # ------------------------------------------------------------------
    # 베이스 에셋 로딩
    # ------------------------------------------------------------------

    def load_base_assets(self) -> tuple[dict[str, Any] | None, list[str]]:
        """
        base/ 디렉터리의 모든 에셋 로딩.

        Returns:
            (assets_dict, missing_files_list)
            assets_dict가 None이면 필수 파일 누락.
        """
        if not self._data_path.exists():
            return None, [f"데이터 파일 없음: {self._data_path}"]

        zf = self._open_zip()
        missing = [name for name in STEP1_REQUIRED if not self._exists(f"base/{name}")]
        if missing:
            return None, missing

        assets: dict[str, Any] = {}

        # 필수 파일 로딩
        for name in STEP1_REQUIRED:
            arc = f"base/{name}"
            if name.endswith(".parquet"):
                assets[name] = self._read_parquet(arc)
            else:
                assets[name] = self._read_json(arc)

        # 선택 파일 그룹별 로딩
        optional_groups: list[tuple[str, list[str]]] = [
            ("step3", STEP3_OPTIONAL),
            ("step7", STEP7_OPTIONAL),
            ("step9", STEP9_OPTIONAL),
            ("step10", STEP10_OPTIONAL),
        ]
        for prefix, file_list in optional_groups:
            step_missing: list[str] = []
            for name in file_list:
                arc = f"base/{name}"
                if not self._exists(arc):
                    step_missing.append(name)
                    continue
                if name.endswith(".parquet"):
                    assets[f"{prefix}::{name}"] = self._read_parquet(arc)
                else:
                    assets[f"{prefix}::{name}"] = self._read_json(arc)
            assets[f"{prefix}_missing"] = step_missing

        return assets, []

    # ------------------------------------------------------------------
    # 파티션 데이터 (step15)
    # ------------------------------------------------------------------

    def load_partition_data(self, partition_name: str) -> dict[str, Any]:
        """
        특정 파티션의 step15 데이터 로딩 (캐시 사용).

        Returns:
            {
                'combo': DataFrame,
                'expression': DataFrame,
                'clothing': DataFrame,
                'characteristic': DataFrame,
                'catalog': DataFrame,
                'quality': dict,
            }
        """
        if partition_name in self._step15_cache:
            return self._step15_cache[partition_name]

        data: dict[str, Any] = {}
        prefix = f"partitions/{partition_name}"

        key_map = {
            "event_observed_combo.parquet": "combo",
            "event_expression_cooccurrence.parquet": "expression",
            "event_clothing_cooccurrence.parquet": "clothing",
            "event_characteristic_cooccurrence.parquet": "characteristic",
            "event_catalog.parquet": "catalog",
            "quality_metrics_step15.json": "quality",
        }

        for filename, key in key_map.items():
            arc = f"{prefix}/{filename}"
            if not self._exists(arc):
                data[key] = pd.DataFrame() if filename.endswith(".parquet") else {}
                continue
            if filename.endswith(".parquet"):
                data[key] = self._read_parquet(arc)
            else:
                data[key] = self._read_json(arc)

        self._step15_cache[partition_name] = data
        return data

    def get_available_partitions(self) -> set[str]:
        """ZIP 내 사용 가능한 파티션 목록 스캔."""
        if self._available_partitions is not None:
            return self._available_partitions

        zf = self._open_zip()
        partitions: set[str] = set()
        for name in zf.namelist():
            if name.startswith("partitions/") and "/" in name[len("partitions/"):]:
                partition_name = name[len("partitions/"):].split("/")[0]
                if partition_name:
                    partitions.add(partition_name)

        self._available_partitions = partitions
        return partitions

    # ------------------------------------------------------------------
    # 보조 데이터
    # ------------------------------------------------------------------

    def get_recommendations(self) -> dict:
        """event_recommended_tags.json 로딩 (캐시)."""
        if self._recommendations is not None:
            return self._recommendations
        if self._exists("event_recommended_tags.json"):
            raw = self._read_json("event_recommended_tags.json")
            self._recommendations = raw.get("recommendations", raw)
        else:
            self._recommendations = {}
        return self._recommendations

    def get_event_partition_index(self) -> dict:
        """event_partition_index.json 로딩 (캐시)."""
        if self._event_partition_index is not None:
            return self._event_partition_index
        if self._exists("event_partition_index.json"):
            self._event_partition_index = self._read_json("event_partition_index.json")
        else:
            self._event_partition_index = {}
        return self._event_partition_index

    def get_color_prefixes(self) -> list[str]:
        """color.txt 기반 색상 접두사 목록 (길이 역순 정렬)."""
        if self._color_prefixes is not None:
            return self._color_prefixes
        if self._exists("color.txt"):
            raw = self._read_text("color.txt")
            prefixes: set[str] = set()
            for line in raw.splitlines():
                value = line.strip().lower().replace("_", " ").strip()
                if value:
                    prefixes.add(value)
            self._color_prefixes = sorted(prefixes, key=len, reverse=True)
        else:
            self._color_prefixes = []
        return self._color_prefixes

    def get_partition_row_counts(self) -> dict:
        """partition_row_counts.json 로딩 (캐시)."""
        if self._partition_row_counts is not None:
            return self._partition_row_counts
        if self._exists("partition_row_counts.json"):
            self._partition_row_counts = self._read_json("partition_row_counts.json")
        else:
            self._partition_row_counts = {}
        return self._partition_row_counts

    # ------------------------------------------------------------------
    # 정리
    # ------------------------------------------------------------------

    def clear_partition_cache(self):
        """파티션 캐시 초기화 (메모리 해제)."""
        self._step15_cache.clear()

    def close(self):
        """ZIP 파일 닫기 (공유 파티션 캐시는 유지)."""
        if self._zip_ref is not None:
            try:
                self._zip_ref.close()
            except Exception:
                pass
            self._zip_ref = None
        # _shared_step15_cache는 다른 인스턴스가 재사용하므로 유지
        self._available_partitions = None
        self._recommendations = None
        self._event_partition_index = None
        self._color_prefixes = None
        self._partition_row_counts = None
