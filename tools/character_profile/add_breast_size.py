"""캐릭터별 가슴 크기 분포를 character_analysis.json에 추가한다.

- 소스: output_part_*.parquet (1girl, rating in {s, q, e}, alternate 제외)
- 결과: character_analysis.json 각 캐릭터에 "breast_size" 필드 추가
- 기존 characteristics에서 가슴 크기 태그 제거
"""

import json
import glob
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "tags"
ANALYSIS_PATH = DATA_DIR / "character_analysis.json"
PARQUET_DIR = Path(__file__).resolve().parent

BREAST_TAGS = [
    "flat_chest", "small_breasts", "medium_breasts",
    "large_breasts", "huge_breasts", "gigantic_breasts",
]
BREAST_SET = set(BREAST_TAGS)

VALID_RATINGS = {"s", "q", "e"}


def load_analysis():
    with open(ANALYSIS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_char_lookup(analysis):
    """캐릭터 이름 → (group_key, char_name) 매핑."""
    lookup = {}
    for gk, chars in analysis.items():
        for name, ch in chars.items():
            for alias in ch.get("aliases", []):
                tag_form = alias.replace(" ", "_")
                lookup[tag_form] = (gk, name)
            tag_form = name.replace(" ", "_")
            lookup[tag_form] = (gk, name)
    return lookup


def process_parquets(char_lookup):
    """parquet 파일들을 읽어 캐릭터별 가슴 크기 카운트를 집계."""
    # {(gk, name): {"total_sqe": 0, "flat_chest": 0, ...}}
    stats = defaultdict(lambda: defaultdict(int))

    files = sorted(glob.glob(str(PARQUET_DIR / "output_part_*.parquet")))
    print(f"Processing {len(files)} parquet files...")

    for fi, fpath in enumerate(files):
        df = pd.read_parquet(fpath, columns=[
            "rating", "tag_string_general", "tag_string_character",
        ])

        # 필터: rating in {s, q, e}
        df = df[df["rating"].isin(VALID_RATINGS)]

        # 필터: 1girl
        mask_1girl = df["tag_string_general"].str.contains(r"\b1girl\b", na=False)
        df = df[mask_1girl]

        # 필터: alternate 제외
        mask_alt = df["tag_string_general"].str.contains("alternate", na=False)
        df = df[~mask_alt]

        print(f"  [{fi+1}/{len(files)}] {Path(fpath).name}: {len(df):,} rows after filter")

        for _, row in df.iterrows():
            char_tags = str(row["tag_string_character"]).split(" ")
            gen_tags = set(str(row["tag_string_general"]).split(" "))

            # 이 행의 가슴 크기 태그
            row_breast = gen_tags & BREAST_SET

            for ctag in char_tags:
                ctag = ctag.strip()
                if not ctag:
                    continue
                key = char_lookup.get(ctag)
                if key is None:
                    continue

                stats[key]["total_sqe"] += 1
                for bt in row_breast:
                    stats[key][bt] += 1

    return stats


def main():
    print("Loading character_analysis.json...")
    analysis = load_analysis()
    char_lookup = build_char_lookup(analysis)
    print(f"Character lookup: {len(char_lookup)} entries")

    stats = process_parquets(char_lookup)
    print(f"\nCharacters with breast data: {len(stats)}")

    # analysis에 breast_size 추가 + characteristics에서 가슴 태그 제거
    updated = 0
    for (gk, name), bdata in stats.items():
        ch = analysis.get(gk, {}).get(name)
        if ch is None:
            continue

        total = bdata["total_sqe"]
        if total == 0:
            continue

        breast_dist = []
        for tag in BREAST_TAGS:
            count = bdata.get(tag, 0)
            if count > 0:
                breast_dist.append({
                    "tag": tag.replace("_", " "),
                    "count": count,
                    "pct": round(count / total * 100, 1),
                })

        ch["breast_size"] = {
            "total_rated_rows": total,
            "distribution": breast_dist,
        }

        # characteristics에서 가슴 크기 태그 제거
        if "characteristics" in ch:
            ch["characteristics"] = [
                e for e in ch["characteristics"]
                if e["tag"].replace(" ", "_") not in BREAST_SET
            ]

        updated += 1

    print(f"Updated {updated} characters")

    # 저장
    with open(ANALYSIS_PATH, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    print(f"Saved to {ANALYSIS_PATH}")


if __name__ == "__main__":
    main()
