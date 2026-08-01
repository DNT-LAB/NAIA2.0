"""신 데이터(output_part_*.parquet)에서 캐릭터 추출 전체 파이프라인.

Step 1: 신 데이터 변환 + 필터링 → filtered / alternate parquet 생성
Step 2: general 태그 정리
Step 3: multi-character 해소
Step 4: 전체 1girl 캐릭터 빈도 추출
Step 5: copyright 그룹 구축 (Danbooru 규칙 기반)
Step 6: 캐릭터 분석

Usage:
    python build_from_new_data.py
"""

import json
import argparse
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TAGS_DIR = DATA_DIR / "tags"
TAGLIST_DIR = DATA_DIR / "taglist"
INPUT_DIR = BASE_DIR / ".experimental"

INPUT_FILES = sorted(INPUT_DIR.glob("output_part_*.parquet"))

FILTERED_PATH = TAGS_DIR / "1girl_solo_filtered.parquet"
ALTERNATE_PATH = TAGS_DIR / "1girl_solo_alternate.parquet"
FREQ_PATH = TAGS_DIR / "1girl_char_frequency.json"
GROUPS_PATH = TAGS_DIR / "copyright_groups.json"
ANALYSIS_PATH = TAGS_DIR / "character_analysis.json"

MIN_ROWS = 30

# 빈도 cutoff
PC_CUTOFF = 30    # Personal Color: >= 30%
CH_CUTOFF = 50    # Characteristics: >= 50%
BREAST_CUTOFF = 20  # Breast size 예외: > 20% (최빈 1개만)

BREAST_SIZE_TAGS = {
    "flat chest", "small breasts", "medium breasts",
    "large breasts", "huge breasts", "gigantic breasts",
}


# ═══════════════════════════════════════════════════════
# 태그 변환 유틸
# ═══════════════════════════════════════════════════════


def convert_tags(raw):
    """공백 구분 + 언더스코어 → 쉼표 구분 + 공백."""
    if pd.isna(raw) or raw.strip() == "":
        return raw
    tags = [t.replace("_", " ") for t in raw.split()]
    return ", ".join(tags)


def convert_dataframe(df):
    """신 데이터 DataFrame을 구 형식으로 변환."""
    result = pd.DataFrame()
    result["id"] = df["id"]
    result["copyright"] = df["tag_string_copyright"].apply(convert_tags)
    result["character"] = df["tag_string_character"].apply(convert_tags)
    result["artist"] = df["tag_string_artist"].apply(convert_tags)
    result["general"] = df["tag_string_general"].apply(convert_tags)
    result["meta"] = df["tag_string_meta"].apply(convert_tags)
    result["rating"] = df["rating"]
    result["score"] = df["score"]
    result["created_at"] = df["created_at"]
    result["image_width"] = df["image_width"].astype("int32")
    result["image_height"] = df["image_height"].astype("int32")
    return result


# ═══════════════════════════════════════════════════════
# Step 1: 변환 + 필터링
# ═══════════════════════════════════════════════════════


def filter_general_base(general_str):
    """1girl + solo 필수, cosplay 거부."""
    if pd.isna(general_str):
        return False
    tags = {t.strip() for t in general_str.split(",")}
    if "1girl" not in tags or "solo" not in tags:
        return False
    for tag in tags:
        if "cosplay" in tag:
            return False
    return True


def filter_general_filtered(general_str):
    """1girl + solo 필수, alternate/cosplay 거부."""
    if pd.isna(general_str):
        return False
    tags = {t.strip() for t in general_str.split(",")}
    if "1girl" not in tags or "solo" not in tags:
        return False
    for tag in tags:
        if "alternate" in tag or "cosplay" in tag:
            return False
    return True


def filter_general_alternate(general_str):
    """1girl + solo + official alternate costume 필수, cosplay 거부."""
    if pd.isna(general_str):
        return False
    tags = {t.strip() for t in general_str.split(",")}
    if "1girl" not in tags or "solo" not in tags:
        return False
    if "official alternate costume" not in tags:
        return False
    for tag in tags:
        if "cosplay" in tag:
            return False
    return True


def step1_build_parquets():
    """신 데이터에서 filtered / alternate parquet 생성."""
    print("=" * 60)
    print("Step 1: Build parquets from new data")
    print("=" * 60)

    filtered_frames = []
    alternate_frames = []
    total_original = 0

    for i, f in enumerate(INPUT_FILES):
        df_raw = pd.read_parquet(f, engine="pyarrow")
        total_original += len(df_raw)

        # 변환
        df = convert_dataframe(df_raw)
        del df_raw

        # original 제외
        df = df[df["copyright"] != "original"]

        # --- filtered ---
        df_f = df[df["rating"].isin(["g", "s"])]
        mask_f = df_f["general"].apply(filter_general_filtered)
        df_f = df_f[mask_f]
        filtered_frames.append(df_f)

        # --- alternate ---
        df_a = df[df["rating"].isin(["g", "s", "q"])]
        mask_a = df_a["general"].apply(filter_general_alternate)
        df_a = df_a[mask_a]
        alternate_frames.append(df_a)

        print(f"  [{i+1}/{len(INPUT_FILES)}] {f.name}: {len(df)} converted"
              f" -> filtered {len(df_f)}, alternate {len(df_a)}")

    result_f = pd.concat(filtered_frames, ignore_index=True)
    result_f.to_parquet(FILTERED_PATH, engine="pyarrow", index=False)
    print(f"\n  filtered: {len(result_f)} rows -> {FILTERED_PATH.name}")

    result_a = pd.concat(alternate_frames, ignore_index=True)
    result_a.to_parquet(ALTERNATE_PATH, engine="pyarrow", index=False)
    print(f"  alternate: {len(result_a)} rows -> {ALTERNATE_PATH.name}")
    print(f"  (from {total_original} original rows)\n")

    return len(result_f), len(result_a)


# ═══════════════════════════════════════════════════════
# Step 2: General 태그 정리
# ═══════════════════════════════════════════════════════


def step2_clean_general():
    """general 컬럼에서 캐릭터 무관 태그 제거."""
    print("=" * 60)
    print("Step 2: Clean general tags")
    print("=" * 60)

    # 블랙리스트
    removal = set()
    with open(TAGLIST_DIR / "location_tags.json", "r", encoding="utf-8") as f:
        removal.update(json.load(f)["tags"])
    with open(TAGLIST_DIR / "expression_tags.json", "r", encoding="utf-8") as f:
        expr = json.load(f)
        for key in ("modifiers",):
            if isinstance(expr.get(key), list):
                removal.update(expr[key])
        for group_tags in expr.get("groups", {}).values():
            if isinstance(group_tags, list):
                removal.update(group_tags)
    with open(TAGLIST_DIR / "pose_action_tags.json", "r", encoding="utf-8") as f:
        pose = json.load(f)
        for cat_tags in pose.get("categories", {}).values():
            if isinstance(cat_tags, list):
                removal.update(cat_tags)
    print(f"  blacklist: {len(removal)} tags")

    # 화이트리스트
    known = set()
    with open(DATA_DIR / "characteristic_list.txt", "r", encoding="utf-8") as f:
        known.update(line.strip() for line in f if line.strip())
    with open(DATA_DIR / "clothes_list.txt", "r", encoding="utf-8") as f:
        known.update(line.strip() for line in f if line.strip())
    with open(TAGS_DIR / "unique_tags.json", "r", encoding="utf-8") as f:
        known.update(json.load(f).keys())
    print(f"  whitelist: {len(known)} tags")

    def clean(general_str):
        if pd.isna(general_str):
            return general_str
        tags = [t.strip() for t in general_str.split(",") if t.strip()]
        cleaned = [t for t in tags if t not in removal and t in known]
        return ", ".join(cleaned)

    for path in [FILTERED_PATH, ALTERNATE_PATH]:
        df = pd.read_parquet(path, engine="pyarrow")
        before_avg = df["general"].apply(
            lambda s: len([t for t in s.split(",") if t.strip()]) if pd.notna(s) else 0
        ).mean()
        df["general"] = df["general"].apply(clean)
        after_avg = df["general"].apply(
            lambda s: len([t for t in s.split(",") if t.strip()]) if pd.notna(s) else 0
        ).mean()
        empty = df["general"].apply(lambda s: s.strip() == "" if pd.notna(s) else True)
        dropped = empty.sum()
        df = df[~empty]
        df.to_parquet(path, engine="pyarrow", index=False)
        print(f"  {path.name}: avg {before_avg:.1f} -> {after_avg:.1f} tags/row, "
              f"dropped {dropped} empty, {len(df)} rows")
    print()


# ═══════════════════════════════════════════════════════
# Step 3: Multi-character 해소
# ═══════════════════════════════════════════════════════


def step3_resolve_multi_characters():
    """multi-character 엔트리를 primary 캐릭터로 해소."""
    print("=" * 60)
    print("Step 3: Resolve multi-character entries")
    print("=" * 60)

    for path in [FILTERED_PATH, ALTERNATE_PATH]:
        df = pd.read_parquet(path, engine="pyarrow")
        single_mask = ~df["character"].str.contains(",", na=False)
        standalone_counts = df[single_mask]["character"].value_counts().to_dict()

        multi_mask = df["character"].str.contains(",", na=False)
        multi_count = multi_mask.sum()

        def resolve(char_val):
            if pd.isna(char_val) or "," not in char_val:
                return char_val
            parts = [p.strip() for p in char_val.split(",")]
            best = max(parts, key=lambda p: standalone_counts.get(p, 0))
            if standalone_counts.get(best, 0) == 0:
                return parts[0]
            return best

        if multi_count > 0:
            df.loc[multi_mask, "character"] = df.loc[multi_mask, "character"].apply(resolve)

        df.to_parquet(path, engine="pyarrow", index=False)
        remaining = df["character"].str.contains(",", na=False).sum()
        print(f"  {path.name}: resolved {multi_count}, remaining {remaining}")
    print()


# ═══════════════════════════════════════════════════════
# Step 4: 전체 1girl 캐릭터 빈도
# ═══════════════════════════════════════════════════════


def step4_extract_1girl_frequency():
    """신 데이터에서 전체 1girl 캐릭터 빈도 추출."""
    print("=" * 60)
    print("Step 4: Extract 1girl character frequency")
    print("=" * 60)

    char_counter = Counter()
    total = 0

    for i, f in enumerate(INPUT_FILES):
        df = pd.read_parquet(f, columns=["tag_string_general", "tag_string_character"],
                             engine="pyarrow")
        mask = df["tag_string_general"].str.contains("1girl", na=False)
        df = df[mask]
        total += len(df)

        for raw_char in df["tag_string_character"].dropna():
            char_val = convert_tags(raw_char)
            if "," in char_val:
                # standalone 해소는 나중에
                char_counter[char_val] += 1
            else:
                char_counter[char_val] += 1

        print(f"  [{i+1}/{len(INPUT_FILES)}] {f.name}: {len(df)} 1girl rows")

    # standalone 기반 해소
    standalone = {k: v for k, v in char_counter.items() if "," not in k}
    resolved = dict(standalone)
    for k, v in char_counter.items():
        if "," not in k:
            continue
        parts = [p.strip() for p in k.split(",")]
        best = max(parts, key=lambda p: standalone.get(p, 0))
        if standalone.get(best, 0) == 0:
            best = parts[0]
        resolved[best] = resolved.get(best, 0) + v

    sorted_chars = dict(sorted(resolved.items(), key=lambda x: -x[1]))
    with open(FREQ_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted_chars, f, ensure_ascii=False, indent=2)

    over_30 = sum(1 for v in sorted_chars.values() if v >= MIN_ROWS)
    print(f"\n  Total 1girl rows: {total}")
    print(f"  Unique characters (resolved): {len(sorted_chars)}")
    print(f"  Characters >= {MIN_ROWS} rows: {over_30}")
    print(f"  Saved: {FREQ_PATH.name}\n")

    return sorted_chars


# ═══════════════════════════════════════════════════════
# Step 5: Copyright 그룹 구축 (Danbooru 규칙 기반)
# ═══════════════════════════════════════════════════════


def build_copyright_tag_freq(df):
    """개별 copyright 태그의 빈도 카운터 구축."""
    all_tags = []
    has_cp = df["copyright"].notna() & (df["copyright"].str.strip() != "")
    for val in df[has_cp]["copyright"]:
        all_tags.extend([t.strip() for t in val.split(",")])
    return Counter(all_tags)


def resolve_copyright_group(cp_val, series_tags, tag_freq):
    """Danbooru copyright 계층 규칙으로 그룹 키 결정.

    1. (series) 태그가 있으면 해당 태그를 그룹으로
    2. 없으면 최빈 개별 태그를 그룹으로
    """
    if pd.isna(cp_val) or cp_val.strip() == "":
        return None
    parts = [t.strip() for t in cp_val.split(",")]
    for p in parts:
        if p in series_tags:
            return p
    return max(parts, key=lambda p: tag_freq.get(p, 0))


def step5_build_copyright_groups(resolved_freq):
    """copyright 그룹 구축 (Danbooru 규칙 기반)."""
    print("=" * 60)
    print("Step 5: Build copyright groups")
    print("=" * 60)

    df = pd.read_parquet(FILTERED_PATH, engine="pyarrow")

    # 개별 copyright 태그 빈도
    tag_freq = build_copyright_tag_freq(df)
    series_tags = {t for t in tag_freq if t.endswith("(series)")}
    print(f"  Individual copyright tags: {len(tag_freq)}")
    print(f"  (series) tags: {len(series_tags)}")

    # 그룹 결정
    df["_group"] = df["copyright"].apply(
        lambda x: resolve_copyright_group(x, series_tags, tag_freq)
    )

    # original 제외, 미분류 제외
    df = df[(df["_group"].notna()) & (df["_group"] != "original")]

    # vectorized groupby로 캐릭터 집계
    has_char = df["character"].notna() & (df["character"].str.strip() != "")
    gc = df[has_char].groupby(["_group", "character"]).size().reset_index(name="count")
    gc = gc[gc["count"] >= MIN_ROWS]
    gc["full_count"] = gc["character"].map(resolved_freq).fillna(0)
    gc = gc[gc["full_count"] >= MIN_ROWS]

    # 그룹 JSON 구축
    groups = {
        "_schema": {
            "description": "Copyright별 캐릭터 분류 (Danbooru 규칙 기반).",
            "group_key": "(series) 태그 우선, 없으면 최빈 개별 copyright 태그",
            "character_format": {
                "name": "대표 캐릭터명",
                "aliases": "parquet character 컬럼 매칭용 별칭 리스트",
            },
        }
    }

    total_chars = 0
    for gk, gdf in gc.groupby("_group"):
        girl_list = [{"name": name, "aliases": [name]} for name in gdf["character"]]
        groups[gk] = {"girl": girl_list, "boy": []}
        total_chars += len(girl_list)

    with open(GROUPS_PATH, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)

    group_count = len([k for k in groups if not k.startswith("_")])
    print(f"\n  {group_count} groups, {total_chars} characters")
    print(f"  Saved: {GROUPS_PATH.name}\n")


# ═══════════════════════════════════════════════════════
# Step 6: 캐릭터 분석
# ═══════════════════════════════════════════════════════


def load_classification_sets():
    color_keywords = [
        "aqua", "black", "blonde", "blue", "brown", "dark", "green", "grey",
        "gray", "light", "multicolored", "orange", "pink", "purple", "red",
        "silver", "white", "yellow", "gradient", "streaked", "two-tone",
        "colored", "platinum",
    ]
    with open(DATA_DIR / "characteristic_list.txt", "r", encoding="utf-8") as f:
        all_chars = {line.strip() for line in f if line.strip()}
    with open(DATA_DIR / "clothes_list.txt", "r", encoding="utf-8") as f:
        all_clothes = {line.strip() for line in f if line.strip()}

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


def analyze_character(df_char, classify):
    total = len(df_char)
    if total == 0:
        return None

    tag_counter = Counter()
    for tags_str in df_char["general"]:
        if pd.isna(tags_str):
            continue
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        tag_counter.update(tags)

    all_pc = []
    all_ch = []

    for tag, cnt in tag_counter.most_common():
        pct = round(cnt / total * 100, 1)
        entry = {"tag": tag, "count": cnt, "pct": pct}
        if tag in classify["personal_color"]:
            all_pc.append(entry)
        elif tag in classify["characteristics"]:
            all_ch.append(entry)

    # Personal Color: >= PC_CUTOFF%
    filtered_pc = [e for e in all_pc if e["pct"] >= PC_CUTOFF]

    # Characteristics: >= CH_CUTOFF%
    filtered_ch = [e for e in all_ch if e["pct"] >= CH_CUTOFF]

    # Breast size 예외: 최빈 1개, > BREAST_CUTOFF% 이면 포함
    breast_entries = [e for e in all_ch if e["tag"] in BREAST_SIZE_TAGS]
    if breast_entries:
        top_breast = breast_entries[0]  # most_common 순이므로 이미 최빈
        if top_breast["pct"] > BREAST_CUTOFF:
            already = any(e["tag"] == top_breast["tag"] for e in filtered_ch)
            if not already:
                filtered_ch.append(top_breast)

    return {
        "total_rows": total,
        "personal_color": filtered_pc,
        "characteristics": filtered_ch,
    }


def step6_analyze_characters():
    """캐릭터별 태그 빈도 분석."""
    print("=" * 60)
    print("Step 6: Analyze characters")
    print("=" * 60)

    df = pd.read_parquet(FILTERED_PATH, engine="pyarrow")
    with open(GROUPS_PATH, "r", encoding="utf-8") as f:
        groups = json.load(f)

    classify = load_classification_sets()

    # Danbooru 규칙으로 그룹 재계산
    tag_freq = build_copyright_tag_freq(df)
    series_tags = {t for t in tag_freq if t.endswith("(series)")}
    df["_group"] = df["copyright"].apply(
        lambda x: resolve_copyright_group(x, series_tags, tag_freq)
    )

    copyrights = [k for k in groups if not k.startswith("_")]

    output = {}
    total_chars = 0

    for cp in copyrights:
        girl_list = groups[cp].get("girl", [])
        if not girl_list:
            continue

        df_cp = df[df["_group"] == cp]
        if len(df_cp) == 0:
            continue

        cp_result = {}
        for char_def in girl_list:
            name = char_def["name"]
            aliases = char_def["aliases"]
            df_char = df_cp[df_cp["character"].isin(aliases)]
            if len(df_char) < MIN_ROWS:
                continue
            analysis = analyze_character(df_char, classify)
            if analysis:
                analysis["gender"] = "girl"
                analysis["aliases"] = aliases
                cp_result[name] = analysis

        if cp_result:
            output[cp] = cp_result
            total_chars += len(cp_result)

    # 상위 캐릭터/그룹 출력
    for cp in sorted(output.keys(), key=lambda x: -sum(
            d["total_rows"] for d in output[x].values())):
        chars = sorted(output[cp].items(), key=lambda x: -x[1]["total_rows"])
        top3 = ", ".join(f"{n}({d['total_rows']})" for n, d in chars[:3])
        print(f"  [{cp}] {len(chars)} chars: {top3}")

    with open(ANALYSIS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n  Total: {total_chars} characters across {len(output)} groups")
    print(f"  Saved: {ANALYSIS_PATH.name}\n")


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════


def main():
    print(f"Input files: {len(INPUT_FILES)}")
    for f in INPUT_FILES:
        print(f"  {f.name}")
    print()

    step1_build_parquets()
    step2_clean_general()
    step3_resolve_multi_characters()
    resolved_freq = step4_extract_1girl_frequency()
    step5_build_copyright_groups(resolved_freq)
    step6_analyze_characters()

    print("=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
