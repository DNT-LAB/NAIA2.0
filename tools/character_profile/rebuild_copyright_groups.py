"""copyright_groups.json을 parquet의 실제 copyright 분포에서 재구축.

다중 copyright 값(쉼표 구분)을 시리즈 키워드로 그룹핑.
예: "fate/grand order, fate (series)" → "fate" 그룹
"""

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TAGS_DIR = DATA_DIR / "tags"
FILTERED_PATH = TAGS_DIR / "1girl_solo_filtered.parquet"
FREQ_PATH = TAGS_DIR / "1girl_char_frequency.json"
GROUPS_PATH = TAGS_DIR / "copyright_groups.json"

MIN_ROWS = 30

# 시리즈 그룹 정의: (그룹 키, 매칭 키워드)
# copyright 값에 키워드가 포함되면 해당 그룹으로 분류
# 순서 중요: 먼저 매칭된 것이 우선
SERIES_GROUPS = [
    ("touhou", "touhou"),
    ("kantai collection", "kantai collection"),
    ("blue archive", "blue archive"),
    ("fate", "fate"),
    ("genshin impact", "genshin impact"),
    ("arknights", "arknights"),
    ("umamusume", "umamusume"),
    ("hololive", "hololive"),
    ("idolmaster", "idolmaster"),
    ("azur lane", "azur lane"),
    ("vocaloid", "vocaloid"),
    ("honkai: star rail", "honkai: star rail"),
    ("honkai impact 3rd", "honkai impact 3rd"),
    ("indie virtual youtuber", "indie virtual youtuber"),
    ("pokemon", "pokemon"),
    ("love live!", "love live!"),
    ("girls und panzer", "girls und panzer"),
    ("girls' frontline", "girls' frontline"),
    ("nijisanji", "nijisanji"),
    ("zenless zone zero", "zenless zone zero"),
    ("kemono friends", "kemono friends"),
    ("granblue fantasy", "granblue fantasy"),
    ("fire emblem", "fire emblem"),
    ("final fantasy", "final fantasy"),
    ("wuthering waves", "wuthering waves"),
    ("chainsaw man", "chainsaw man"),
    ("princess connect!", "princess connect!"),
    ("goddess of victory: nikke", "nikke"),
    ("bocchi the rock!", "bocchi the rock!"),
    ("danganronpa", "danganronpa"),
    ("re:zero", "re:zero"),
    ("bang dream!", "bang dream!"),
    ("xenoblade", "xenoblade"),
    ("yu-gi-oh!", "yu-gi-oh!"),
    ("one piece", "one piece"),
    ("mahou shoujo madoka magica", "madoka magica"),
    ("boku no hero academia", "boku no hero academia"),
    ("sousou no frieren", "sousou no frieren"),
    ("limbus company", "project moon"),
    ("ragnarok online", "ragnarok online"),
    ("go-toubun no hanayome", "go-toubun no hanayome"),
    ("reverse:1999", "reverse:1999"),
    ("league of legends", "league of legends"),
    ("precure", "precure"),
    ("splatoon", "splatoon"),
    ("spy x family", "spy x family"),
    ("sword art online", "sword art online"),
    ("elden ring", "elden ring"),
    ("naruto", "naruto"),
    ("dungeon meshi", "dungeon meshi"),
    ("lycoris recoil", "lycoris recoil"),
    ("kono subarashii sekai ni shukufuku wo!", "kono subarashii sekai"),
    ("senki zesshou symphogear", "symphogear"),
    ("mushoku tensei", "mushoku tensei"),
    ("oshi no ko", "oshi no ko"),
    ("black lagoon", "black lagoon"),
    ("evangelion", "evangelion"),
    ("voiceroid", "voiceroid"),
    ("touken ranbu", "touken ranbu"),
    ("original", "original"),
]


def classify_copyright(cp_val):
    """copyright 값을 시리즈 그룹으로 분류."""
    if pd.isna(cp_val):
        return None
    cp_lower = cp_val.lower()
    for group_key, keyword in SERIES_GROUPS:
        if keyword.lower() in cp_lower:
            return group_key
    return None


def main():
    print("Loading data...")
    df = pd.read_parquet(FILTERED_PATH, engine="pyarrow")
    print(f"  filtered: {len(df)} rows")

    # 전체 1girl 빈도 (검증용)
    with open(FREQ_PATH, "r", encoding="utf-8") as f:
        full_freq = json.load(f)
    standalone_freq = {k: v for k, v in full_freq.items() if "," not in k}
    resolved_freq = dict(standalone_freq)
    for k, v in full_freq.items():
        if "," not in k:
            continue
        parts = [p.strip() for p in k.split(",")]
        best = max(parts, key=lambda p: standalone_freq.get(p, 0))
        if standalone_freq.get(best, 0) == 0:
            best = parts[0]
        resolved_freq[best] = resolved_freq.get(best, 0) + v

    # copyright 그룹 분류
    df["_group"] = df["copyright"].apply(classify_copyright)

    classified = df["_group"].notna().sum()
    unclassified = df["_group"].isna().sum()
    print(f"  classified: {classified} rows ({classified/len(df)*100:.1f}%)")
    print(f"  unclassified: {unclassified} rows ({unclassified/len(df)*100:.1f}%)")

    # 미분류 상위 확인
    if unclassified > 0:
        unc = df[df["_group"].isna()]["copyright"].value_counts().head(15)
        print(f"\n  Top unclassified copyrights:")
        for cp, cnt in unc.items():
            print(f"    {cnt:>6}: {cp}")

    # 그룹별 캐릭터 집계
    groups = {
        "_schema": {
            "description": "Copyright별 캐릭터 분류. girl/boy에 해당하지 않는 캐릭터는 제외.",
            "character_format": {
                "name": "대표 캐릭터명 (출력/식별용)",
                "aliases": "parquet character 컬럼 매칭용 별칭 리스트",
            },
        }
    }

    total_chars = 0
    group_keys = sorted(df[df["_group"].notna()]["_group"].unique())

    # original 제외
    group_keys = [g for g in group_keys if g != "original"]

    print(f"\n{len(group_keys)} copyright groups:\n")

    for gk in group_keys:
        df_gk = df[df["_group"] == gk]
        char_counts = df_gk["character"].value_counts()

        girl_list = []
        for name, cnt in char_counts.items():
            if pd.isna(name) or name.strip() == "":
                continue
            full_cnt = resolved_freq.get(name, 0)
            if cnt >= MIN_ROWS and full_cnt >= MIN_ROWS:
                girl_list.append({"name": name, "aliases": [name]})

        groups[gk] = {"girl": girl_list, "boy": []}
        total_chars += len(girl_list)
        print(f"  [{gk}] {len(df_gk)} rows -> {len(girl_list)} characters")

    # 저장
    with open(GROUPS_PATH, "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)

    print(f"\nDone: {total_chars} characters across {len(group_keys)} groups")
    print(f"Saved: {GROUPS_PATH}")


if __name__ == "__main__":
    main()
