"""output_part_00~08.parquet에서 character_analysis.json 재생성.

rebuild_pipeline.py 복제본. 데이터 소스만 output_part 파일로 교체.
output_part는 Danbooru 원본 형식(공백 구분 + 언더스코어)이므로 전처리 포함.

기존 character_analysis.json의 breast_size / alternates 필드는 보존.

Usage:
    cd .experimental
    python rebuild_from_output_parts.py
"""

import json
import os
from collections import Counter
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PARTS_DIR = BASE_DIR / ".experimental"

# 입력: output_part_00 ~ output_part_08
PART_FILES = sorted(PARTS_DIR.glob("output_part_0[0-8].parquet"))

# 출력 (프로덕션 경로)
GROUPS_PATH = DATA_DIR / "copyright_groups.json"
ANALYSIS_PATH = DATA_DIR / "character_analysis.json"

MIN_ROWS = 30
PC_CUTOFF = 30   # Personal Color: >= 30%
CH_CUTOFF = 50   # Characteristics: >= 50%

BREAST_SIZE_TAGS = {
    "flat chest", "small breasts", "medium breasts",
    "large breasts", "huge breasts", "gigantic breasts",
}
BODY_TYPE_TAGS = {"loli", "mature female"}

EVENT_PREFIXES = [
    "comiket", "comic market", "comitia", "reitaisai",
    "c10", "c9", "c8",
]


# ═══════════════════════════════════════════════════════
# 전처리: output_part 태그 변환
# ═══════════════════════════════════════════════════════


def convert_tags(raw):
    """공백 구분 + 언더스코어 → 쉼표 구분 + 공백.

    변환 순서: "tag_a tag_b" → "tag_a, tag_b" → "tag a, tag b"
    """
    if pd.isna(raw) or not isinstance(raw, str) or raw.strip() == "":
        return ""
    tags = raw.split(" ")
    joined = ", ".join(tags)       # " " → ", "
    return joined.replace("_", " ")  # "_" → " "


def load_output_parts():
    """output_part_00~08 로드 + 태그 변환 + 1girl solo 필터링."""
    if not PART_FILES:
        raise FileNotFoundError("output_part_0[0-8].parquet 파일이 없습니다.")

    print(f"Loading {len(PART_FILES)} parquet files...")
    frames = []
    total_raw = 0

    for f in PART_FILES:
        df = pd.read_parquet(f, columns=[
            "tag_string_general", "tag_string_character",
            "tag_string_copyright", "rating",
        ], engine="pyarrow")
        total_raw += len(df)
        frames.append(df)
        print(f"  {f.name}: {len(df):,} rows")

    df = pd.concat(frames, ignore_index=True)
    print(f"  Total raw: {total_raw:,} rows\n")

    # 태그 변환
    print("Converting tags...")
    df["general"] = df["tag_string_general"].apply(convert_tags)
    df["character"] = df["tag_string_character"].apply(convert_tags)
    df["copyright"] = df["tag_string_copyright"].apply(convert_tags)
    df.drop(columns=["tag_string_general", "tag_string_character",
                      "tag_string_copyright"], inplace=True)

    # 필터: rating g/s
    df = df[df["rating"].isin(["g", "s"])]
    print(f"  After rating filter (g/s): {len(df):,}")

    # 필터: 1girl + solo, no alternate/cosplay
    def filter_general(general_str):
        if not general_str:
            return False
        tags = {t.strip() for t in general_str.split(",")}
        if "1girl" not in tags or "solo" not in tags:
            return False
        for tag in tags:
            if "alternate" in tag or "cosplay" in tag:
                return False
        return True

    mask = df["general"].apply(filter_general)
    df = df[mask]
    print(f"  After 1girl+solo filter: {len(df):,}")

    # 필터: copyright != original
    df = df[df["copyright"] != "original"]
    print(f"  After original exclusion: {len(df):,}\n")

    df.drop(columns=["rating"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def build_char_frequency(df):
    """캐릭터 빈도 카운팅 + multi-character 해소."""
    print("Building character frequency...")
    char_counter = Counter()
    has_char = df["character"].notna() & (df["character"].str.strip() != "")
    for val in df[has_char]["character"]:
        char_counter[val] += 1

    # multi-character 해소: "char1, char2" → standalone 빈도 최고로
    standalone = {k: v for k, v in char_counter.items() if ", " not in k}
    resolved = Counter(standalone)
    for multi_key, cnt in char_counter.items():
        if ", " not in multi_key:
            continue
        parts = [p.strip() for p in multi_key.split(",")]
        best = max(parts, key=lambda p: standalone.get(p, 0))
        resolved[best] += cnt

    print(f"  Raw: {len(char_counter):,} entries → Resolved: {len(resolved):,}")
    print(f"  Top 5: {resolved.most_common(5)}\n")
    return resolved


# ═══════════════════════════════════════════════════════
# Copyright 그룹 구축
# ═══════════════════════════════════════════════════════


def build_copyright_tag_freq(df):
    all_tags = []
    has_cp = df["copyright"].notna() & (df["copyright"].str.strip() != "")
    for val in df[has_cp]["copyright"]:
        all_tags.extend([t.strip() for t in val.split(",")])
    return Counter(all_tags)


def _is_event_tag(tag):
    t = tag.lower()
    return any(t.startswith(p) for p in EVENT_PREFIXES)


def resolve_copyright_group(cp_val, series_tags, tag_freq):
    if pd.isna(cp_val) or not isinstance(cp_val, str) or cp_val.strip() == "":
        return None
    parts = [t.strip() for t in cp_val.split(",")]
    for p in parts:
        if p in series_tags:
            return p
    non_event = [p for p in parts if not _is_event_tag(p)]
    if non_event:
        return max(non_event, key=lambda p: tag_freq.get(p, 0))
    return max(parts, key=lambda p: tag_freq.get(p, 0))


def build_copyright_groups(df, resolved_freq):
    print("=" * 60)
    print("Building copyright groups")
    print("=" * 60)

    tag_freq = build_copyright_tag_freq(df)
    series_tags = {t for t in tag_freq if t.endswith("(series)")}
    print(f"  Copyright tags: {len(tag_freq)}, (series) tags: {len(series_tags)}")

    df["_group"] = df["copyright"].apply(
        lambda x: resolve_copyright_group(x, series_tags, tag_freq)
    )

    df_filtered = df[(df["_group"].notna()) & (df["_group"] != "original")]
    has_char = df_filtered["character"].notna() & (df_filtered["character"].str.strip() != "")
    gc = df_filtered[has_char].groupby(["_group", "character"]).size().reset_index(name="count")
    gc = gc[gc["count"] >= MIN_ROWS]
    gc["full_count"] = gc["character"].map(resolved_freq).fillna(0)
    gc = gc[gc["full_count"] >= MIN_ROWS]

    groups = {
        "_schema": {
            "description": "Copyright별 캐릭터 분류 (output_part 기반 재생성).",
        }
    }

    total_chars = 0
    for gk, gdf in gc.groupby("_group"):
        girl_list = [{"name": name, "aliases": [name]} for name in gdf["character"]]
        groups[gk] = {"girl": girl_list, "boy": []}
        total_chars += len(girl_list)

    group_count = len([k for k in groups if not k.startswith("_")])
    print(f"  {group_count} groups, {total_chars} characters\n")

    return groups, tag_freq, series_tags


# ═══════════════════════════════════════════════════════
# 캐릭터 분석
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
            if tag in BREAST_SIZE_TAGS:
                continue
            all_ch.append(entry)

    filtered_pc = [e for e in all_pc if e["pct"] >= PC_CUTOFF]
    filtered_ch = [e for e in all_ch if e["pct"] >= CH_CUTOFF]

    return {
        "total_rows": total,
        "personal_color": filtered_pc,
        "characteristics": filtered_ch,
    }


def run_analysis(df, groups, old_analysis):
    print("=" * 60)
    print("Analyzing characters")
    print("=" * 60)

    classify = load_classification_sets()

    tag_freq = build_copyright_tag_freq(df)
    series_tags = {t for t in tag_freq if t.endswith("(series)")}
    df["_group"] = df["copyright"].apply(
        lambda x: resolve_copyright_group(x, series_tags, tag_freq)
    )

    copyrights = [k for k in groups if not k.startswith("_")]

    output = {}
    total_chars = 0
    preserved_bs = 0
    preserved_alt = 0
    preserved_bt = 0

    for cp in copyrights:
        girl_list = groups[cp].get("girl", [])
        if not girl_list:
            continue

        df_cp = df[df["_group"] == cp]
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

                # 기존 breast_size / alternates / body-type 보존
                old_cp = old_analysis.get(cp, {})
                old_char = old_cp.get(name, {})
                if "breast_size" in old_char:
                    analysis["breast_size"] = old_char["breast_size"]
                    preserved_bs += 1
                if "alternates" in old_char:
                    analysis["alternates"] = old_char["alternates"]
                    preserved_alt += 1
                old_ch = old_char.get("characteristics", [])
                for old_entry in old_ch:
                    if old_entry["tag"] in BODY_TYPE_TAGS:
                        analysis["characteristics"].append(old_entry)
                        preserved_bt += 1

                cp_result[name] = analysis

        if cp_result:
            output[cp] = cp_result
            total_chars += len(cp_result)

    # 상위 그룹 출력
    sorted_groups = sorted(output.keys(), key=lambda x: -sum(
        d["total_rows"] for d in output[x].values()))
    for cp in sorted_groups[:20]:
        chars = sorted(output[cp].items(), key=lambda x: -x[1]["total_rows"])
        top3 = ", ".join(f"{n}({d['total_rows']})" for n, d in chars[:3])
        print(f"  [{cp}] {len(chars)} chars: {top3}")
    if len(output) > 20:
        print(f"  ... ({len(output) - 20} more groups)")

    print(f"\n  Total: {total_chars} characters across {len(output)} groups")
    print(f"  Preserved breast_size: {preserved_bs}")
    print(f"  Preserved alternates: {preserved_alt}")
    print(f"  Preserved body-type: {preserved_bt}")

    return output


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════


def main():
    print(f"Source: output_part_00 ~ output_part_08")
    print(f"Output groups:   {GROUPS_PATH}")
    print(f"Output analysis: {ANALYSIS_PATH}")
    print()

    # 기존 character_analysis.json 로드 (breast_size/alternates 보존용)
    old_analysis = {}
    if ANALYSIS_PATH.exists():
        with open(ANALYSIS_PATH, "r", encoding="utf-8") as f:
            old_analysis = json.load(f)
        print(f"Loaded existing analysis: {len(old_analysis)} groups\n")

    # 1. 로드 + 전처리 + 필터링
    df = load_output_parts()

    # 2. 캐릭터 빈도
    resolved_freq = build_char_frequency(df)

    # 3. Copyright 그룹 구축
    groups, tag_freq, series_tags = build_copyright_groups(df, resolved_freq)

    # 4. 그룹 저장
    with open(GROUPS_PATH, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {GROUPS_PATH}\n")

    # 5. 캐릭터 분석
    output = run_analysis(df, groups, old_analysis)

    # 6. 저장
    with open(ANALYSIS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {ANALYSIS_PATH}")

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
