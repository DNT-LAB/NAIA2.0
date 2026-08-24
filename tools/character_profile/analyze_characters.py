"""캐릭터 태그 빈도 분석 스크립트.

copyright_groups.json의 각 copyright에 대해:
1. parquet에서 캐릭터 발견 (상위 N명)
2. 캐릭터별 태그 빈도 집계
3. Personal Color / Characteristics / Key Clothes 분류
4. 결과를 JSON으로 출력

Usage:
    python analyze_characters.py [--min-rows 50] [--top-n 30]
                                 [--min-pct-color 30] [--min-pct-char 20]
"""

import json
import argparse
from collections import Counter
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TAGS_DIR = DATA_DIR / "tags"

FILTERED_PATH = TAGS_DIR / "1girl_solo_filtered.parquet"
ALTERNATE_PATH = TAGS_DIR / "1girl_solo_alternate.parquet"
GROUPS_PATH = TAGS_DIR / "copyright_groups.json"
OUTPUT_PATH = TAGS_DIR / "character_analysis.json"

# 퍼센트 문턱. 이 스크립트에는 오랫동안 개수 상한(`--top-n`)만 있었고, 그래서 배포된
# `data/character_analysis.json` 의 2,874종(21.3%)이 0.3% 짜리 태그까지 달고 있었다.
# ⚠️ 세 곳이 **같은 값이어야 한다** - 어긋나면 증분으로 들어온 캐릭터와 원본 캐릭터의
#    잣대가 달라진다:
#      tools/build_character_profile_increment.py  (증분 빌드)
#      tools/prune_character_profile_gate.py       (사후 가지치기 · 검사)
#      여기                                        (전체 재빌드)
MIN_PCT_COLOR = 30.0
MIN_PCT_CHAR = 20.0

# ─── 태그 분류용 사전 로드 ───


def load_classification_sets():
    """태그를 카테고리별로 분류하기 위한 set들을 로드."""
    with open(DATA_DIR / "characteristic_list.txt", "r", encoding="utf-8") as f:
        all_chars = {line.strip() for line in f if line.strip()}

    with open(DATA_DIR / "clothes_list.txt", "r", encoding="utf-8") as f:
        all_clothes = {line.strip() for line in f if line.strip()}

    # 색상 키워드
    color_keywords = [
        "aqua", "black", "blonde", "blue", "brown", "dark", "green", "grey",
        "gray", "light", "multicolored", "orange", "pink", "purple", "red",
        "silver", "white", "yellow", "gradient", "streaked", "two-tone",
        "colored", "platinum",
    ]

    hair_colors = {t for t in all_chars if "hair" in t
                   and any(c in t for c in color_keywords)}
    eye_colors = {t for t in all_chars if ("eyes" in t or "pupils" in t)
                  and any(c in t for c in color_keywords)}
    personal_colors = hair_colors | eye_colors | {"heterochromia"}

    characteristics = all_chars - personal_colors

    return {
        "personal_color": personal_colors,
        "characteristics": characteristics,
        "clothes": all_clothes,
    }


# ─── 단일 캐릭터 분석 ───


def analyze_character_tags(df_char, classify, top_n=30,
                           min_pct_color=MIN_PCT_COLOR, min_pct_char=MIN_PCT_CHAR):
    """캐릭터 DataFrame에서 태그 빈도를 분석하고 분류."""
    total = len(df_char)
    if total == 0:
        return None

    tag_counter = Counter()
    for tags_str in df_char["general"]:
        if pd.isna(tags_str):
            continue
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        tag_counter.update(tags)

    # 분류별 상위 태그 추출
    result = {
        "total_rows": total,
        "personal_color": [],
        "characteristics": [],
        "key_clothes": [],
    }

    for tag, cnt in tag_counter.most_common():
        pct = round(cnt / total * 100, 1)
        entry = {"tag": tag, "count": cnt, "pct": pct}

        if tag in classify["personal_color"]:
            bucket, floor = result["personal_color"], min_pct_color
        elif tag in classify["clothes"]:
            bucket, floor = result["key_clothes"], min_pct_char
        elif tag in classify["characteristics"]:
            bucket, floor = result["characteristics"], min_pct_char
        else:
            continue
        # ⚠️ 개수 상한만으로는 모자란다. `most_common()` 은 내림차순이라 상한에 걸리기
        #    전까지 **0.3% 짜리도 다 담긴다** - 129행짜리 `lacrimosa (nte)` 가 색 15종을
        #    달고 `red hair 0.8%`(1장)까지 프롬프트에 넣었던 이유다(제보 2026-08-24).
        #    소비자에 자체 문턱이 없으므로(`character_viewer_service.py` 의 프롬프트
        #    조립) 이 파일이 유일한 관문이다. 문턱을 상한보다 **먼저** 본다.
        if pct < floor:
            continue
        if len(bucket) < top_n:
            bucket.append(entry)

    return result


# ─── 메인 ───


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-rows", type=int, default=50,
                        help="최소 행 수 (이 미만의 캐릭터는 건너뜀)")
    parser.add_argument("--top-n", type=int, default=30,
                        help="카테고리별 상위 태그 수")
    parser.add_argument("--min-pct-color", type=float, default=MIN_PCT_COLOR,
                        help="personal_color 최소 비율 (기본 30)")
    parser.add_argument("--min-pct-char", type=float, default=MIN_PCT_CHAR,
                        help="characteristics / key_clothes 최소 비율 (기본 20)")
    args = parser.parse_args()

    print("Loading datasets...")
    df_filtered = pd.read_parquet(FILTERED_PATH, engine="pyarrow")
    print(f"  filtered: {len(df_filtered)} rows")

    with open(GROUPS_PATH, "r", encoding="utf-8") as f:
        groups = json.load(f)

    classify = load_classification_sets()
    print(f"  personal_color: {len(classify['personal_color'])} tags")
    print(f"  characteristics: {len(classify['characteristics'])} tags")
    print(f"  clothes: {len(classify['clothes'])} tags")

    copyrights = [k for k in groups if not k.startswith("_")]
    print(f"\nProcessing {len(copyrights)} copyright groups...\n")

    output = {}

    for cp in copyrights:
        df_cp = df_filtered[df_filtered["copyright"] == cp]
        if len(df_cp) == 0:
            print(f"[{cp}] No data, skipping")
            continue

        # 캐릭터 발견: character 컬럼의 value_counts
        char_counts = df_cp["character"].value_counts()
        # 기존 aliases가 있으면 매칭, 없으면 자동 발견
        group_info = groups[cp]
        discovered_girls = []
        discovered_boys = []

        # 현재는 groups가 비어있으므로 자동 발견 모드
        has_defined_chars = (
            any(isinstance(c, dict) for c in group_info.get("girl", []))
            or any(isinstance(c, dict) for c in group_info.get("boy", []))
        )

        if has_defined_chars:
            # 정의된 캐릭터의 aliases로 매칭
            all_chars = []
            for gender in ("girl", "boy"):
                for char_def in group_info.get(gender, []):
                    if isinstance(char_def, dict):
                        all_chars.append((char_def["name"], char_def["aliases"], gender))
        else:
            # 자동 발견: min_rows 이상인 캐릭터 전부 수집
            all_chars = []
            for char_name, cnt in char_counts.items():
                if pd.isna(char_name) or char_name.strip() == "":
                    continue
                if cnt >= args.min_rows:
                    all_chars.append((char_name, [char_name], "unknown"))

        print(f"[{cp}] {len(df_cp)} rows, {len(all_chars)} characters (>= {args.min_rows} rows)")

        cp_result = {}
        for char_name, aliases, gender in all_chars:
            # aliases에 해당하는 행 필터링
            mask = df_cp["character"].isin(aliases)
            df_char = df_cp[mask]

            if len(df_char) < args.min_rows:
                continue

            analysis = analyze_character_tags(
                df_char, classify, args.top_n,
                min_pct_color=args.min_pct_color, min_pct_char=args.min_pct_char)
            if analysis:
                analysis["gender"] = gender
                analysis["aliases"] = aliases
                cp_result[char_name] = analysis

        if cp_result:
            output[cp] = cp_result
            # 캐릭터별 요약 출력
            for name, data in sorted(cp_result.items(),
                                     key=lambda x: -x[1]["total_rows"]):
                pc = ", ".join(e["tag"] for e in data["personal_color"][:3])
                ch = ", ".join(e["tag"] for e in data["characteristics"][:3])
                cl = ", ".join(e["tag"] for e in data["key_clothes"][:3])
                print(f"  {name} ({data['total_rows']} rows)")
                print(f"    Color: {pc}")
                print(f"    Chars: {ch}")
                print(f"    Cloth: {cl}")

        print()

    # 저장
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Saved: {OUTPUT_PATH}")
    print(f"Total: {sum(len(v) for v in output.values())} characters across {len(output)} copyrights")


if __name__ == "__main__":
    main()
