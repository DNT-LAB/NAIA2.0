"""multi-character 엔트리를 primary 캐릭터로 해소.

1girl+solo 데이터셋에서 character 컬럼에 2+ 이름이 있으면
1other(유령, 마스코트, 인형 등)가 섞인 것이므로,
standalone 빈도가 가장 높은 "real" 캐릭터로 축소.

처리 후 copyright_groups.json, character_analysis.json 재생성.
"""

import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TAGS_DIR = DATA_DIR / "tags"

TARGETS = [
    TAGS_DIR / "1girl_solo_filtered.parquet",
    TAGS_DIR / "1girl_solo_alternate.parquet",
]


def resolve_characters(df):
    """multi-character 엔트리를 primary 캐릭터로 해소."""
    # 1. standalone 빈도 맵 구축
    single_mask = ~df["character"].str.contains(",", na=False)
    standalone_counts = df[single_mask]["character"].value_counts().to_dict()

    # 2. multi-character 행 해소
    multi_mask = df["character"].str.contains(",", na=False)
    multi_count = multi_mask.sum()

    if multi_count == 0:
        return df, 0

    def resolve(char_val):
        if pd.isna(char_val) or "," not in char_val:
            return char_val
        parts = [p.strip() for p in char_val.split(",")]
        # standalone 빈도가 가장 높은 파트 선택
        best = max(parts, key=lambda p: standalone_counts.get(p, 0))
        # 모든 파트가 standalone 0이면 첫 번째 파트
        if standalone_counts.get(best, 0) == 0:
            return parts[0]
        return best

    df.loc[multi_mask, "character"] = df.loc[multi_mask, "character"].apply(resolve)
    return df, multi_count


def main():
    for path in TARGETS:
        if not path.exists():
            print(f"Skipping (not found): {path.name}")
            continue

        print(f"--- {path.name} ---")
        df = pd.read_parquet(path, engine="pyarrow")
        print(f"  rows: {len(df)}")

        df, resolved = resolve_characters(df)
        print(f"  resolved {resolved} multi-character entries")

        df.to_parquet(path, engine="pyarrow", index=False)
        print(f"  saved: {path.name}")

        # 검증
        remaining_multi = df["character"].str.contains(",", na=False).sum()
        print(f"  remaining multi-character: {remaining_multi}")
        print()


if __name__ == "__main__":
    main()
