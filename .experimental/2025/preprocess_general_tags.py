"""
output_part_00~08.parquet 전처리 스크립트 v2
- id, rating, tag_string_general만 추출
- tag normalize: '_' → ' ', space-delimited → comma-delimited
- taglist/*.json + clothes_list.txt + characteristic_list.txt 기반 축 분류
- overlap_classification.json 기반 76개 오분류 수정
- tag_axis_overrides.json 기반 core axis override 적용
- person_count 컬럼: #boy → #girl → #other 순서, solo/multiple 계열 보존
- 출력: .experimental/2025/classified/classified_part_NN.parquet
- 부산물: overlap_report.json, unclassified_freq.json
"""

import json
import time
from pathlib import Path
from collections import defaultdict, Counter

import pandas as pd
import pyarrow.parquet as pq

from core.tag_axis_registry import (
    PRIMARY_AXES,
    apply_axis_overrides,
    is_person_count_tag,
    normalize_tag,
    person_count_sort_key,
)

ROOT = Path(r"C:\VNR\NAIA2.0")
TAGLIST_DIR = ROOT / "data" / "taglist"
DATA_DIR = ROOT / "data"
INPUT_DIR = ROOT / ".experimental"
OUTPUT_DIR = ROOT / ".experimental" / "2025" / "classified"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CATEGORIES = list(PRIMARY_AXES)

ALL_COLUMNS = CATEGORIES + ["person_count", "person_focus", "uncategorized"]

# 충돌 시 우선순위 (높을수록 우선)
PRIORITY = {
    "clothing": 60,
    "expression": 50,
    "pose_action": 40,
    "characteristic": 35,
    "location": 30,
    "object": 20,
    "meta": 10,
    "sexual_or_nsfw": 45,
}

# expression_tags.json에 누락된 이모티콘/기호 (수동 보충)
_EXTRA_EXPRESSION = {"?", "!", "!!", "??", "| |", "+++", "<|> <|>", "\\n/", "3 3", "x<"}


def load_flat_tags(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data.get("tags", []))


def load_expression_tags(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tags = set(data.get("modifiers", []))
    for group_tags in data.get("groups", {}).values():
        tags.update(group_tags)
    return tags


def load_pose_action_tags(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tags = set()
    for cat_tags in data.get("categories", {}).values():
        tags.update(cat_tags)
    tags.update(data.get("uncategorized", []))
    return tags


def load_clothing_tags_from_regions(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tags = set()
    for region_tags in data.get("regions", {}).values():
        tags.update(region_tags)
    tags.update(data.get("unassigned_region", []))
    return tags


def load_txt_list(path: Path) -> set[str]:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return {line.strip() for line in lines if line.strip()}


def load_overrides() -> dict[str, str]:
    """overlap_classification.json의 misclassified 항목에서 tag→suggested 매핑 생성."""
    override_path = OUTPUT_DIR / "overlap_classification.json"
    if not override_path.exists():
        print("[warn] overlap_classification.json not found, skipping overrides")
        return {}
    data = json.loads(override_path.read_text(encoding="utf-8"))
    overrides = {}
    for item in data.get("misclassified", []):
        overrides[normalize_tag(item["tag"])] = item["suggested"]
    print(f"[overrides] Loaded {len(overrides)} misclassification overrides")
    return overrides


def build_tag_lookup() -> tuple[dict[str, str], dict[str, list[str]]]:
    clothing_full = load_txt_list(DATA_DIR / "clothes_list.txt")
    clothing_full |= load_clothing_tags_from_regions(TAGLIST_DIR / "clothing_regions.json")

    expr_tags = load_expression_tags(TAGLIST_DIR / "expression_tags.json")
    expr_tags |= _EXTRA_EXPRESSION

    category_sets: dict[str, set[str]] = {
        "expression": expr_tags,
        "pose_action": load_pose_action_tags(TAGLIST_DIR / "pose_action_tags.json"),
        "location": load_flat_tags(TAGLIST_DIR / "location_tags.json"),
        "meta": load_flat_tags(TAGLIST_DIR / "meta_tags.json"),
        "object": load_flat_tags(TAGLIST_DIR / "object_tags.json"),
        "clothing": clothing_full,
        "characteristic": load_txt_list(DATA_DIR / "characteristic_list.txt"),
    }

    # 충돌 감지 + 우선순위 해결
    tag_to_cats: dict[str, list[str]] = defaultdict(list)
    for cat, tags in category_sets.items():
        for t in tags:
            tag_to_cats[normalize_tag(t)].append(cat)

    overlaps: dict[str, list[str]] = {}
    tag_to_category: dict[str, str] = {}

    for tag, cats in tag_to_cats.items():
        if len(cats) > 1:
            overlaps[tag] = sorted(cats)
            winner = max(cats, key=lambda c: PRIORITY[c])
            tag_to_category[tag] = winner
        else:
            tag_to_category[tag] = cats[0]

    # Codex 오분류 수정 적용
    overrides = load_overrides()
    applied = 0
    for tag, suggested in overrides.items():
        if tag in tag_to_category and tag_to_category[tag] != suggested:
            tag_to_category[tag] = suggested
            applied += 1
    print(f"[overrides] Applied {applied} overrides (changed category)")

    axis_result = apply_axis_overrides(
        tag_to_category,
        allowed_axes=set(CATEGORIES + ["person_count", "person_focus"]),
    )
    print(
        "[axis_overrides] "
        f"loaded={axis_result.records_loaded}, applied={axis_result.applied}, "
        f"added={axis_result.added}, changed={axis_result.changed}, "
        f"unchanged={axis_result.unchanged}, skipped_axis={axis_result.skipped_axis}"
    )

    print(f"[lookup] Total classified tags: {len(tag_to_category)}")
    print(f"[lookup] Overlaps: {len(overlaps)}")

    return tag_to_category, overlaps


def classify_row(tag_string: str, lookup: dict[str, str]) -> dict[str, str]:
    if not tag_string or pd.isna(tag_string):
        return {col: "" for col in ALL_COLUMNS}

    buckets: dict[str, list[str]] = {col: [] for col in ALL_COLUMNS}
    # Numeric person_count tags stay first, then override-based composition tags.
    person_entries: list[tuple[tuple[int, int, str], str]] = []

    for raw_index, raw_tag in enumerate(tag_string.split(" ")):
        tag = normalize_tag(raw_tag)

        if is_person_count_tag(tag):
            person_order, _ = person_count_sort_key(tag)
            person_entries.append(((0, person_order, tag), tag))
            continue

        cat = lookup.get(tag, "uncategorized")
        if cat not in buckets:
            cat = "uncategorized"
        if cat == "person_count":
            person_entries.append(((1, raw_index, tag), tag))
            continue
        buckets[cat].append(tag)

    # person_count: boy → girl → other 순서 정렬
    person_entries.sort(key=lambda x: x[0])
    buckets["person_count"].extend(tag for _, tag in person_entries)

    return {col: ", ".join(tags) for col, tags in buckets.items()}


def process_file(
    part_idx: int,
    lookup: dict[str, str],
    unclassified_counter: Counter,
) -> int:
    input_path = INPUT_DIR / f"output_part_{part_idx:02d}.parquet"
    output_path = OUTPUT_DIR / f"classified_part_{part_idx:02d}.parquet"

    t0 = time.time()
    print(f"\n[part {part_idx:02d}] Reading {input_path.name}...")

    table = pq.read_table(input_path, columns=["id", "rating", "tag_string_general"])
    df = table.to_pandas()
    del table
    print(f"  rows: {len(df):,}, read: {time.time() - t0:.1f}s")

    t1 = time.time()
    results = df["tag_string_general"].apply(lambda s: classify_row(s, lookup))
    classified = pd.DataFrame(results.tolist())

    for tags_str in classified["uncategorized"]:
        if tags_str:
            for t in tags_str.split(", "):
                unclassified_counter[t] += 1

    out = pd.concat([df[["id", "rating"]], classified], axis=1)
    print(f"  classify: {time.time() - t1:.1f}s")

    t2 = time.time()
    out.to_parquet(output_path, index=False, engine="pyarrow")
    print(f"  write: {time.time() - t2:.1f}s, size: {output_path.stat().st_size / 1e6:.1f}MB")

    return len(df)


def main():
    print("=" * 60)
    print("output_part 전처리 v2: 카테고리 분류 + 오분류 수정 + person_count")
    print("=" * 60)

    lookup, overlaps = build_tag_lookup()

    report_path = OUTPUT_DIR / "overlap_report.json"
    report_path.write_text(
        json.dumps(overlaps, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n[saved] {report_path}")

    unclassified_counter: Counter = Counter()
    total_rows = 0
    t_start = time.time()

    for i in range(9):
        total_rows += process_file(i, lookup, unclassified_counter)

    unc_path = OUTPUT_DIR / "unclassified_freq.json"
    top_unc = dict(unclassified_counter.most_common(3000))
    unc_path.write_text(
        json.dumps(top_unc, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    elapsed = time.time() - t_start
    print(f"\n{'=' * 60}")
    print(f"Done. {total_rows:,} rows, {elapsed:.0f}s total")
    print(f"Unique unclassified tags: {len(unclassified_counter):,}")
    print(f"Top 20 unclassified:")
    for tag, cnt in unclassified_counter.most_common(20):
        print(f"  {tag}: {cnt:,}")
    print(f"\nOutput: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
