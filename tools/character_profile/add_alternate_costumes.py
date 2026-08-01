"""캐릭터별 official_alternate_costume variant를 분석하여 character_analysis.json에 추가.

- 소스: official_alt_costume_1girl_solo.parquet
- 각 variant별 personal_color, characteristics, attire(clothes) 추출
- character_analysis.json에 "alternates" 필드 추가
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TAGS_DIR = DATA_DIR / "tags"
ANALYSIS_PATH = TAGS_DIR / "character_analysis.json"
PARQUET_PATH = Path(__file__).resolve().parent / "official_alt_costume_1girl_solo.parquet"

CLOTHES_PATH = DATA_DIR / "clothes_list.txt"
CHARS_PATH = DATA_DIR / "characteristic_list.txt"

# 가슴 크기 태그 (characteristics에서 제외, breast_size로 별도 관리)
BREAST_TAGS = {"flat_chest", "small_breasts", "medium_breasts",
               "large_breasts", "huge_breasts", "gigantic_breasts"}

# Personal Color에 해당하는 패턴 (eyes, hair 색상)
PC_PATTERNS = re.compile(
    r"(aqua|black|blue|brown|green|grey|orange|purple|pink|red|white|yellow|amber|"
    r"light_blue|light_brown|light_green|light_purple|dark_blue|silver|gold|blonde|"
    r"multicolored|heterochromia|gradient|streaked|two-tone|split-color|colored_inner)_"
    r"(eyes|hair|eyelashes)|"
    r"multicolored_(hair|eyes)|heterochromia|albino"
)

# 무시할 메타/구도 태그
IGNORE_TAGS = {
    "1girl", "solo", "official_alternate_costume", "virtual_youtuber",
    "looking_at_viewer", "smile", "open_mouth", "closed_mouth", "blush",
    "simple_background", "white_background", "grey_background", "black_background",
    "gradient_background", "blue_background", "pink_background",
    "cowboy_shot", "upper_body", "full_body", "portrait", "close-up",
    "standing", "sitting", "from_above", "from_below", "from_side", "from_behind",
    "breasts", "collarbone", "navel", "armpits", "cleavage", "midriff",
    "holding", "hand_up", "hand_on_hip", "arms_up", "hands_on_hips",
    "outdoors", "indoors", "sky", "day", "night", "water", "tree", "grass",
    ":d", ":o", ":)", ";)", "^^",
}

MIN_PCT = 10.0     # variant 태그 최소 출현율
MIN_ROWS = 5       # variant 최소 행 수
MIN_CLOTHES_PCT = 15.0  # clothes 태그 최소 출현율


def load_tag_sets():
    """clothes_list.txt, characteristic_list.txt를 set으로 로드."""
    with open(CLOTHES_PATH, "r", encoding="utf-8") as f:
        clothes = {line.strip().replace(" ", "_") for line in f if line.strip()}
    with open(CHARS_PATH, "r", encoding="utf-8") as f:
        chars = {line.strip().replace(" ", "_") for line in f if line.strip()}
    # breast 태그는 characteristics에서 제외
    chars -= BREAST_TAGS
    return clothes, chars


def classify_tag(tag, clothes_set, chars_set):
    """태그를 pc/ch/clothes/ignore로 분류."""
    if tag in IGNORE_TAGS:
        return None
    if PC_PATTERNS.fullmatch(tag):
        return "pc"
    if tag in BREAST_TAGS:
        return None  # 별도 관리
    if tag in chars_set:
        return "ch"
    if tag in clothes_set:
        return "clothes"
    # 색상+의상 복합 태그 (예: white_shirt, blue_skirt)
    if "_" in tag:
        suffix = "_".join(tag.split("_")[1:])
        if suffix in clothes_set:
            return "clothes"
    return None


def extract_variants(df, char_lookup):
    """parquet에서 캐릭터별 variant 데이터를 추출.

    지원 패턴:
      1) prefix_(variant)                  — gawr_gura_(casual)
      2) prefix_(variant)_(copyright)      — type_95_(summer_cicada)_(girls'_frontline)
      3) prefix_(copyright)_(variant)      — fujimaru_ritsuka_(female)_(brilliant_summer)
    """
    # {(gk, base_name): {variant_label: [row_tags_list, ...]}}
    variant_rows = defaultdict(lambda: defaultdict(list))

    for _, row in df.iterrows():
        char_tags = str(row["tag_string_character"]).split(" ")
        gen_tags = str(row["tag_string_general"]).split(" ")

        # base 캐릭터 식별
        base_key = None
        variant_labels = []
        for ct in char_tags:
            ct = ct.strip()
            if not ct:
                continue

            if "(" not in ct or ")" not in ct:
                # 괄호 없는 태그 → 그대로 lookup
                if ct in char_lookup and base_key is None:
                    base_key = char_lookup[ct]
                continue

            # 괄호 그룹 추출
            groups = re.findall(r"\(([^)]+)\)", ct)
            prefix = ct[:ct.index("(")].rstrip("_")

            if len(groups) >= 2:
                # 패턴 2/3: 어떤 group이 copyright(base)이고 어떤 것이 variant인지 탐색
                resolved = False

                # 시도 1: prefix_(last_group) as base — GFL 등
                last_group = groups[-1]
                base_candidate = f"{prefix}_({last_group})"
                if base_candidate in char_lookup:
                    base_key = char_lookup[base_candidate]
                    for g in groups[:-1]:
                        variant_labels.append(f"({g})")
                    resolved = True

                # 시도 2: prefix_(other_group) as base — Fate, VTuber 등
                if not resolved:
                    for i, g in enumerate(groups):
                        candidate = f"{prefix}_({g})"
                        if candidate in char_lookup:
                            base_key = char_lookup[candidate]
                            for j, og in enumerate(groups):
                                if j != i:
                                    variant_labels.append(f"({og})")
                            resolved = True
                            break

                # 시도 3: prefix 자체가 base
                if not resolved and prefix in char_lookup:
                    base_key = char_lookup[prefix]
                    for g in groups:
                        variant_labels.append(f"({g})")
                    resolved = True

                # 전체 태그가 base 캐릭터 자체일 수 있음
                if not resolved:
                    if ct in char_lookup and base_key is None:
                        base_key = char_lookup[ct]

            elif len(groups) == 1:
                # 패턴 1: prefix_(variant) 또는 prefix_(copyright) (base 캐릭터)
                if prefix in char_lookup:
                    base_key = char_lookup[prefix]
                    variant_labels.append(f"({groups[0]})")
                else:
                    # prefix_(group) 전체가 base 캐릭터 이름
                    full_tag = f"{prefix}_({groups[0]})"
                    if full_tag in char_lookup and base_key is None:
                        base_key = char_lookup[full_tag]

        if base_key is None:
            continue

        if not variant_labels:
            continue

        for label in variant_labels:
            variant_rows[base_key][label].append(gen_tags)

    return variant_rows


def analyze_variants(variant_rows, clothes_set, chars_set):
    """variant별 pc/ch/clothes 태그를 집계."""
    results = {}  # {(gk, name): {"variants": [...]}}

    for (gk, name), variants in variant_rows.items():
        variant_list = []

        for label, rows_list in sorted(variants.items(), key=lambda x: -len(x[1])):
            n_rows = len(rows_list)
            if n_rows < MIN_ROWS:
                continue

            # 태그별 카운트
            pc_counter = Counter()
            ch_counter = Counter()
            clothes_counter = Counter()

            for gen_tags in rows_list:
                for tag in gen_tags:
                    cat = classify_tag(tag, clothes_set, chars_set)
                    if cat == "pc":
                        pc_counter[tag] += 1
                    elif cat == "ch":
                        ch_counter[tag] += 1
                    elif cat == "clothes":
                        clothes_counter[tag] += 1

            def build_list(counter, min_pct):
                items = []
                for tag, cnt in counter.most_common():
                    pct = round(cnt / n_rows * 100, 1)
                    if pct < min_pct:
                        break
                    items.append({
                        "tag": tag.replace("_", " "),
                        "count": cnt,
                        "pct": pct,
                    })
                return items

            pc_list = build_list(pc_counter, MIN_PCT)
            ch_list = build_list(ch_counter, MIN_PCT)
            clothes_list = build_list(clothes_counter, MIN_CLOTHES_PCT)

            # 라벨 정리: (casual) -> casual
            clean_label = label.strip("()")

            variant_list.append({
                "label": clean_label,
                "rows": n_rows,
                "personal_color": pc_list,
                "characteristics": ch_list,
                "attire": clothes_list,
            })

        if variant_list:
            results[(gk, name)] = variant_list

    return results


def main():
    print("Loading tag sets...")
    clothes_set, chars_set = load_tag_sets()
    print(f"  clothes: {len(clothes_set)}, characteristics: {len(chars_set)}")

    print("Loading character_analysis.json...")
    with open(ANALYSIS_PATH, "r", encoding="utf-8") as f:
        analysis = json.load(f)

    # 캐릭터 lookup (underscore form -> (gk, name))
    char_lookup = {}
    for gk, chars in analysis.items():
        for name, ch in chars.items():
            tag_form = name.replace(" ", "_")
            char_lookup[tag_form] = (gk, name)
            for alias in ch.get("aliases", []):
                char_lookup[alias.replace(" ", "_")] = (gk, name)

    print(f"  lookup: {len(char_lookup)} entries")

    print("Loading parquet...")
    df = pd.read_parquet(PARQUET_PATH,
                         columns=["tag_string_general", "tag_string_character"])
    print(f"  {len(df):,} rows")

    print("Extracting variants...")
    variant_rows = extract_variants(df, char_lookup)
    print(f"  {len(variant_rows)} characters with variants")

    print("Analyzing variants...")
    results = analyze_variants(variant_rows, clothes_set, chars_set)
    print(f"  {len(results)} characters with valid variant data")

    # analysis에 반영
    updated = 0
    for (gk, name), variant_list in results.items():
        ch = analysis.get(gk, {}).get(name)
        if ch is None:
            continue
        ch["alternates"] = variant_list
        updated += 1

    print(f"Updated {updated} characters")

    # 샘플 출력
    for (gk, name), variant_list in list(results.items())[:3]:
        print(f"\n--- {gk}/{name} ({len(variant_list)} variants) ---")
        for v in variant_list[:3]:
            print(f"  [{v['label']}] ({v['rows']} rows)")
            print(f"    PC: {[e['tag'] for e in v['personal_color'][:5]]}")
            print(f"    CH: {[e['tag'] for e in v['characteristics'][:5]]}")
            print(f"    Attire: {[e['tag'] for e in v['attire'][:5]]}")

    # 저장
    with open(ANALYSIS_PATH, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {ANALYSIS_PATH}")


if __name__ == "__main__":
    main()
