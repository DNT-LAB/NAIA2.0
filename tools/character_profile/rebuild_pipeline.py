"""Step 5 (copyright 그룹 구축) + Step 6 (캐릭터 분석) 재실행 스크립트.

build_from_new_data.py에서 step 5 + step 6 로직을 추출.
기존 중간 산출물(1girl_solo_filtered.parquet, 1girl_char_frequency.json)을 입력으로 사용하여
copyright_groups.json과 character_analysis.json을 재생성한다.

추가로 data/tags/ 전체 parquet에서 1girl 빈도를 카운팅하여,
solo filtered에서 누락된 캐릭터(full_freq >= 50)를 복구한다.

기존 character_analysis.json의 breast_size / alternates 필드는 보존된다.

Usage:
    cd .experimental
    python rebuild_pipeline.py
"""

import json
import os
from collections import Counter
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TAGS_DIR = DATA_DIR / "tags"
INPUT_DIR = BASE_DIR / ".experimental" / "tag_classifier_project"

# 입력
FILTERED_PATH = INPUT_DIR / "1girl_solo_filtered.parquet"
FREQ_PATH = INPUT_DIR / "1girl_char_frequency.json"

# 출력 (프로덕션 경로)
GROUPS_PATH = DATA_DIR / "copyright_groups.json"
ANALYSIS_PATH = DATA_DIR / "character_analysis.json"

MIN_ROWS = 30
FULL_FREQ_MIN = 50  # data/tags 전체 1girl 빈도 기준

# 빈도 cutoff
PC_CUTOFF = 30    # Personal Color: >= 30%
CH_CUTOFF = 50    # Characteristics: >= 50%

BREAST_SIZE_TAGS = {
    "flat chest", "small breasts", "medium breasts",
    "large breasts", "huge breasts", "gigantic breasts",
}

# body-type 태그: filtered parquet에서 정리되어 없음 → 기존 데이터에서 보존
BODY_TYPE_TAGS = {"loli", "mature female"}

# 이벤트/메타 copyright 태그 패턴 — 그룹 키로 사용 방지
EVENT_PREFIXES = [
    "comiket", "comic market", "comitia", "reitaisai",
    "c10", "c9", "c8",
]


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


def _is_event_tag(tag):
    """이벤트/메타 copyright 태그 여부 판별."""
    t = tag.lower()
    return any(t.startswith(p) for p in EVENT_PREFIXES)


def resolve_copyright_group(cp_val, series_tags, tag_freq):
    """Danbooru copyright 계층 규칙으로 그룹 키 결정.

    1. (series) 태그가 있으면 해당 태그를 그룹으로
    2. 이벤트/메타 태그 제외 후 최빈 개별 태그를 그룹으로
    3. 전부 이벤트 태그면 최빈 태그를 그룹으로
    """
    if pd.isna(cp_val) or cp_val.strip() == "":
        return None
    parts = [t.strip() for t in cp_val.split(",")]
    for p in parts:
        if p in series_tags:
            return p
    non_event = [p for p in parts if not _is_event_tag(p)]
    if non_event:
        return max(non_event, key=lambda p: tag_freq.get(p, 0))
    return max(parts, key=lambda p: tag_freq.get(p, 0))


def step5_build_copyright_groups(df, resolved_freq):
    """copyright 그룹 구축 (Danbooru 규칙 기반)."""
    print("=" * 60)
    print("Step 5: Build copyright groups")
    print("=" * 60)

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
    df_filtered = df[(df["_group"].notna()) & (df["_group"] != "original")]

    # vectorized groupby로 캐릭터 집계
    has_char = df_filtered["character"].notna() & (df_filtered["character"].str.strip() != "")
    gc = df_filtered[has_char].groupby(["_group", "character"]).size().reset_index(name="count")
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

    group_count = len([k for k in groups if not k.startswith("_")])
    print(f"\n  Base: {group_count} groups, {total_chars} characters")

    return groups, tag_freq, series_tags


# ═══════════════════════════════════════════════════════
# Step 5.5: 누락 캐릭터 복구 (data/tags 전체 1girl 빈도)
# ═══════════════════════════════════════════════════════


def build_full_freq():
    """data/tags/ 전체 parquet에서 1girl 행의 캐릭터 빈도 카운팅."""
    files = sorted(TAGS_DIR.glob("*.parquet"))
    char_counter = Counter()
    total = 0

    for i, f in enumerate(files):
        df = pd.read_parquet(f, columns=["general", "character"], engine="pyarrow")
        mask = df["general"].str.contains("1girl", na=False)
        df_1g = df[mask]
        total += len(df_1g)

        has_char = df_1g["character"].notna() & (df_1g["character"].str.strip() != "")
        for val in df_1g[has_char]["character"]:
            char_counter[val] += 1

        if (i + 1) % 30 == 0:
            print(f"    [{i+1}/{len(files)}] {len(char_counter)} chars")

    print(f"    Total 1girl rows: {total}, unique chars: {len(char_counter)}")
    return char_counter


def collect_recovered_rows(target_chars):
    """data/tags/에서 복구 대상 캐릭터들의 1girl 행을 수집."""
    files = sorted(TAGS_DIR.glob("*.parquet"))
    collected = []

    for i, f in enumerate(files):
        df = pd.read_parquet(f, engine="pyarrow")
        mask_1girl = df["general"].str.contains("1girl", na=False)
        mask_char = df["character"].isin(target_chars)
        matched = df[mask_1girl & mask_char]
        if len(matched) > 0:
            collected.append(matched)

        if (i + 1) % 30 == 0:
            rows_so_far = sum(len(c) for c in collected)
            print(f"    [{i+1}/{len(files)}] collected {rows_so_far} rows")

    if collected:
        result = pd.concat(collected, ignore_index=True)
    else:
        result = pd.DataFrame()
    print(f"    Collected {len(result)} rows for {len(target_chars)} target chars")
    return result


def step5b_recover_missing(df, groups, resolved_freq, tag_freq, series_tags):
    """누락 캐릭터 복구: data/tags 전체에서 full_freq >= 50인 캐릭터 추가."""
    print("=" * 60)
    print("Step 5.5: Recover missing characters (full_freq >= 50)")
    print("=" * 60)

    # 현재 그룹에 포함된 캐릭터
    in_groups = set()
    for gk, gdata in groups.items():
        if gk.startswith("_"):
            continue
        for char_def in gdata.get("girl", []):
            in_groups.add(char_def["name"])

    # solo_freq >= 30이지만 그룹에 없는 캐릭터
    missing = {k for k, v in resolved_freq.items() if v >= MIN_ROWS} - in_groups
    print(f"  Missing from groups (solo_freq >= {MIN_ROWS}): {len(missing)}")

    # data/tags 전체에서 1girl 빈도 카운팅
    print("  Building full freq from data/tags/...")
    full_freq = build_full_freq()

    # full_freq >= 50인 누락 캐릭터
    recoverable = {k for k in missing if full_freq.get(k, 0) >= FULL_FREQ_MIN}
    print(f"  Recoverable (full_freq >= {FULL_FREQ_MIN}): {len(recoverable)}")

    if not recoverable:
        print("  Nothing to recover.\n")
        return groups, pd.DataFrame()

    # 누락 캐릭터의 copyright 분류
    # filtered parquet에서 copyright 정보 추출
    no_cp_chars = set()
    char_to_group = {}

    for name in recoverable:
        mask = df["character"] == name
        rows = df[mask]
        if len(rows) == 0:
            no_cp_chars.add(name)
            continue

        cp_empty = rows["copyright"].isna() | (rows["copyright"].str.strip() == "")
        non_empty = rows[~cp_empty]

        if len(non_empty) == 0:
            no_cp_chars.add(name)
            continue

        # copyright가 있는 행에서 그룹 결정
        cp_counter = Counter()
        for cp_val in non_empty["copyright"]:
            group = resolve_copyright_group(cp_val, series_tags, tag_freq)
            if group and group != "original":
                cp_counter[group] += 1

        if cp_counter:
            char_to_group[name] = cp_counter.most_common(1)[0][0]
        else:
            no_cp_chars.add(name)

    print(f"  No copyright → original: {len(no_cp_chars)}")
    print(f"  Has copyright → group:   {len(char_to_group)}")

    # original 그룹에 추가
    if no_cp_chars:
        if "original" not in groups:
            groups["original"] = {"girl": [], "boy": []}
        for name in sorted(no_cp_chars):
            groups["original"]["girl"].append({"name": name, "aliases": [name]})

    # copyright 그룹에 추가
    for name, gk in char_to_group.items():
        if gk not in groups:
            groups[gk] = {"girl": [], "boy": []}
        groups[gk]["girl"].append({"name": name, "aliases": [name]})

    # 저장
    with open(GROUPS_PATH, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)

    group_count = len([k for k in groups if not k.startswith("_")])
    total_chars = sum(
        len(groups[k].get("girl", [])) for k in groups if not k.startswith("_")
    )
    print(f"\n  Final: {group_count} groups, {total_chars} characters")
    print(f"  Saved: {GROUPS_PATH}")

    # 복구 대상 행 수집 (step 6용)
    print("\n  Collecting rows for recovered characters from data/tags/...")
    recovered_rows = collect_recovered_rows(recoverable)

    print()
    return groups, recovered_rows


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
            # breast size 태그는 characteristics에서 제외 (breast_size 필드로 별도 관리)
            if tag in BREAST_SIZE_TAGS:
                continue
            all_ch.append(entry)

    # Personal Color: >= PC_CUTOFF%
    filtered_pc = [e for e in all_pc if e["pct"] >= PC_CUTOFF]

    # Characteristics: >= CH_CUTOFF%
    # (loli/mature female은 filtered parquet에서 정리되어 없음 → step6에서 기존 데이터 merge)
    filtered_ch = [e for e in all_ch if e["pct"] >= CH_CUTOFF]

    return {
        "total_rows": total,
        "personal_color": filtered_pc,
        "characteristics": filtered_ch,
    }


def step6_analyze_characters(df, groups, old_analysis, recovered_rows):
    """캐릭터별 태그 빈도 분석 + 기존 breast_size/alternates 보존."""
    print("=" * 60)
    print("Step 6: Analyze characters")
    print("=" * 60)

    classify = load_classification_sets()

    # Danbooru 규칙으로 그룹 재계산 (filtered parquet용)
    tag_freq = build_copyright_tag_freq(df)
    series_tags = {t for t in tag_freq if t.endswith("(series)")}
    df["_group"] = df["copyright"].apply(
        lambda x: resolve_copyright_group(x, series_tags, tag_freq)
    )

    # 복구된 캐릭터 이름 set
    recovered_chars = set()
    if len(recovered_rows) > 0:
        recovered_chars = set(recovered_rows["character"].unique())

    copyrights = [k for k in groups if not k.startswith("_")]

    output = {}
    total_chars = 0
    recovered_count = 0
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

            # filtered parquet에서 먼저 시도
            df_char = df_cp[df_cp["character"].isin(aliases)]

            if len(df_char) < MIN_ROWS and name in recovered_chars:
                # 복구 대상: data/tags에서 수집한 행 사용
                df_char = recovered_rows[recovered_rows["character"].isin(aliases)]
                if len(df_char) > 0:
                    recovered_count += 1

            if len(df_char) == 0:
                continue

            analysis = analyze_character(df_char, classify)
            if analysis:
                analysis["gender"] = "girl"
                analysis["aliases"] = aliases

                # 기존 breast_size / alternates / body-type 태그 보존
                old_cp = old_analysis.get(cp, {})
                old_char = old_cp.get(name, {})
                if "breast_size" in old_char:
                    analysis["breast_size"] = old_char["breast_size"]
                    preserved_bs += 1
                if "alternates" in old_char:
                    analysis["alternates"] = old_char["alternates"]
                    preserved_alt += 1
                # loli/mature female: filtered parquet에서 정리되어 없음 → 기존 데이터에서 복원
                old_ch = old_char.get("characteristics", [])
                for old_entry in old_ch:
                    if old_entry["tag"] in BODY_TYPE_TAGS:
                        analysis["characteristics"].append(old_entry)
                        preserved_bt += 1

                cp_result[name] = analysis

        if cp_result:
            output[cp] = cp_result
            total_chars += len(cp_result)

    # 상위 캐릭터/그룹 출력
    sorted_groups = sorted(output.keys(), key=lambda x: -sum(
        d["total_rows"] for d in output[x].values()))
    for cp in sorted_groups[:20]:
        chars = sorted(output[cp].items(), key=lambda x: -x[1]["total_rows"])
        top3 = ", ".join(f"{n}({d['total_rows']})" for n, d in chars[:3])
        print(f"  [{cp}] {len(chars)} chars: {top3}")

    print(f"  ... ({len(output) - 20} more groups)")

    with open(ANALYSIS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n  Total: {total_chars} characters across {len(output)} groups")
    print(f"  Recovered from data/tags: {recovered_count}")
    print(f"  Preserved breast_size: {preserved_bs}")
    print(f"  Preserved alternates: {preserved_alt}")
    print(f"  Preserved body-type (loli/mature female): {preserved_bt}")
    print(f"  Saved: {ANALYSIS_PATH}\n")


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════


def main():
    print(f"Input: {FILTERED_PATH}")
    print(f"Freq:  {FREQ_PATH}")
    print(f"Tags:  {TAGS_DIR}")
    print(f"Output groups:   {GROUPS_PATH}")
    print(f"Output analysis: {ANALYSIS_PATH}")
    print()

    # 입력 검증
    if not FILTERED_PATH.exists():
        raise FileNotFoundError(f"Not found: {FILTERED_PATH}")
    if not FREQ_PATH.exists():
        raise FileNotFoundError(f"Not found: {FREQ_PATH}")

    # 기존 character_analysis.json 로드 (breast_size/alternates 보존용)
    old_analysis = {}
    if ANALYSIS_PATH.exists():
        with open(ANALYSIS_PATH, "r", encoding="utf-8") as f:
            old_analysis = json.load(f)
        print(f"Loaded existing analysis: {len(old_analysis)} groups")

    # 캐릭터 빈도 로드
    with open(FREQ_PATH, "r", encoding="utf-8") as f:
        resolved_freq = json.load(f)
    print(f"Character frequency: {len(resolved_freq)} entries")
    print()

    # parquet 로드 (step 5, 6 공유)
    df = pd.read_parquet(FILTERED_PATH, engine="pyarrow")
    print(f"Filtered parquet: {len(df)} rows\n")

    # Step 5: 기본 그룹 구축
    groups, tag_freq, series_tags = step5_build_copyright_groups(df, resolved_freq)

    # Step 5.5: 누락 캐릭터 복구
    groups, recovered_rows = step5b_recover_missing(
        df, groups, resolved_freq, tag_freq, series_tags
    )

    # Step 6: 캐릭터 분석
    step6_analyze_characters(df, groups, old_analysis, recovered_rows)

    print("=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
