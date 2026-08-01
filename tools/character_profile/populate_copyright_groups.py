"""copyright_groups.json에 캐릭터 데이터 채우기.

1girl+solo 데이터셋이므로 모든 캐릭터는 girl로 분류.
복합 캐릭터 값(쉼표 구분)을 기본 캐릭터에 별칭으로 병합.

별칭 병합 규칙:
  - "A, A (variant)" → A의 별칭 (기본 이름이 포함된 경우)
  - "A, companion" → A의 별칭 (A가 기본 캐릭터 중 하나인 경우)
  - 어느 기본 캐릭터에도 매칭 안 되면 별도 처리
"""

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TAGS_DIR = DATA_DIR / "tags"

FILTERED_PATH = TAGS_DIR / "1girl_solo_filtered.parquet"
GROUPS_PATH = TAGS_DIR / "copyright_groups.json"

MIN_ROWS = 50  # 최소 행 수


def collect_characters(char_counts: dict) -> list:
    """캐릭터별 행 수 집계. multi-character는 이미 해소된 상태.

    Args:
        char_counts: {character_name: row_count}

    Returns:
        list of {"name": str, "aliases": list, "total_rows": int}
    """
    groups = {}
    for name, cnt in char_counts.items():
        if pd.isna(name) or name.strip() == "":
            continue
        groups[name] = {"name": name, "aliases": [name], "total_rows": cnt}

    # MIN_ROWS 이상인 것만 유지, total_rows 내림차순 정렬
    result = [g for g in groups.values() if g["total_rows"] >= MIN_ROWS]
    result.sort(key=lambda x: -x["total_rows"])
    return result


def main():
    print("Loading data...")
    df = pd.read_parquet(FILTERED_PATH, engine="pyarrow")
    print(f"  {len(df)} rows")

    with open(GROUPS_PATH, "r", encoding="utf-8") as f:
        groups = json.load(f)

    copyrights = [k for k in groups if not k.startswith("_")]
    print(f"  {len(copyrights)} copyright groups\n")

    total_chars = 0

    for cp in copyrights:
        df_cp = df[df["copyright"] == cp]
        if len(df_cp) == 0:
            print(f"[{cp}] No data, skipping")
            groups[cp]["girl"] = []
            continue

        # 캐릭터별 행 수
        char_counts = df_cp["character"].value_counts().to_dict()

        # 캐릭터 집계 (multi-character는 이미 해소됨)
        merged = collect_characters(char_counts)

        # girl 배열에 채우기 (1girl 데이터셋이므로 전부 girl)
        girl_list = []
        for g in merged:
            girl_list.append({
                "name": g["name"],
                "aliases": g["aliases"],
            })

        groups[cp]["girl"] = girl_list
        # boy는 빈 배열 유지
        total_chars += len(girl_list)

        print(f"[{cp}] {len(df_cp)} rows -> {len(girl_list)} characters")
        # 상위 5명 출력
        for g in merged[:5]:
            alias_info = f" (+{len(g['aliases'])-1} aliases)" if len(g["aliases"]) > 1 else ""
            print(f"  {g['total_rows']:>6} rows: {g['name']}{alias_info}")

    # 저장
    with open(GROUPS_PATH, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)

    print(f"\nDone: {total_chars} characters across {len(copyrights)} copyrights")
    print(f"Saved: {GROUPS_PATH}")


if __name__ == "__main__":
    main()
