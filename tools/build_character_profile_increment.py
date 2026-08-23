"""미색인 캐릭터의 **구성요소 프로필**을 코퍼스 버킷에서 직접 만든다.

캐릭터 태그 툴팁(자동완성)은 세 원천에서 조립된다:

    danbooru_character.character_dict_count   빈도        -> 노출 + cat=='character'
    data/character_analysis.json              구성요소     -> 칩 / Copy All / samples
    data/KR_tags.parquet                      한글 분류/설명 -> 헤더 / 본문 / 한글 검색

이 도구는 가운데 것을 만든다. `tools/character_profile/analyze_characters.py` 와
**같은 분류 규칙**을 쓰되(아래 참조) 원천만 바꾼다 - 원본은 리포 밖에 있는
`1girl_solo_filtered.parquet`(295MB)을 요구해서 이 리포에서 돌릴 수 없다.

⚠️ 원본 스크립트의 `DATA_DIR` 은 이 리포에서 깨져 있다
   (`Path(__file__).parent.parent / "data"` -> `tools/data`, 실제는 리포 루트 `data/`).
   `.experimental` 레이아웃에서 복사된 흔적이다. 여기서는 리포 기준으로 바로잡았다.

식별 필터(사용자 지정, 원본 `build_from_new_data.filter_general_filtered` 와 동일):

    `1girl` ∧ `solo` ∧ 어떤 태그에도 "alternate" 없음 ∧ "cosplay" 없음

의상/헤어 변형(alternate)이 섞이면 "주 구성요소" 가 흐려지기 때문이다.

    python tools/build_character_profile_increment.py --out <dir> \\
        [--min-rows 50] [--top-n 30] [--include-known] [--limit-buckets N]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"

# 색상 키워드 - analyze_characters.load_classification_sets() 원문 그대로.
COLOR_KEYWORDS = [
    "aqua", "black", "blonde", "blue", "brown", "dark", "green", "grey",
    "gray", "light", "multicolored", "orange", "pink", "purple", "red",
    "silver", "white", "yellow", "gradient", "streaked", "two-tone",
    "colored", "platinum",
]
BREAST_TAGS = ("flat chest", "small breasts", "medium breasts",
               "large breasts", "huge breasts", "gigantic breasts")
BREAST_SET = set(BREAST_TAGS)
RATINGS_SQE = {"s", "q", "e"}


def load_classification_sets() -> dict[str, set[str]]:
    """태그 -> 카테고리 집합. analyze_characters.py 와 동일한 규칙."""
    def read_lines(name: str) -> set[str]:
        path = DATA_DIR / name
        if not path.exists():
            raise SystemExit(f"분류 목록이 없습니다: {path}")
        return {line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()}

    all_chars = read_lines("characteristic_list.txt")
    all_clothes = read_lines("clothes_list.txt")

    hair_colors = {t for t in all_chars
                   if "hair" in t and any(c in t for c in COLOR_KEYWORDS)}
    eye_colors = {t for t in all_chars
                  if ("eyes" in t or "pupils" in t) and any(c in t for c in COLOR_KEYWORDS)}
    personal_colors = hair_colors | eye_colors | {"heterochromia"}
    return {
        "personal_color": personal_colors,
        "characteristics": all_chars - personal_colors,
        "clothes": all_clothes,
    }


def known_character_tags() -> set[str]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import danbooru_character

    return {str(k).strip().lower()
            for k in getattr(danbooru_character, "character_dict_count", {})}


def bucket_files(extra: list[Path]) -> list[Path]:
    files = sorted((DATA_DIR / "tags").glob("tags_*.parquet"))
    for d in extra:
        files += sorted(Path(d).glob("tags_*.parquet"))
    return files


def apply_filter(df: pd.DataFrame) -> pd.DataFrame:
    """`1girl` ∧ `solo` ∧ ~alternate ∧ ~cosplay.

    태그는 `, ` 로 결합돼 있다. 온전한 태그 판정은 양끝을 감싸서 하고,
    alternate/cosplay 는 **부분문자열**로 본다(원본과 같은 의미:
    `alternate costume`·`alternate hairstyle`·`cosplay` 계열을 전부 거른다).
    """
    general = df["general"].fillna("").astype(str)
    padded = ", " + general + ", "
    keep = padded.str.contains(", 1girl, ", regex=False)
    keep &= padded.str.contains(", solo, ", regex=False)
    keep &= ~general.str.contains("alternate", regex=False)
    keep &= ~general.str.contains("cosplay", regex=False)
    return df[keep]


def split_names(value) -> list[str]:
    if not value:
        return []
    return [t.strip() for t in str(value).split(", ") if t.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--corpus", action="append", default=[],
                    help="추가 버킷 디렉터리(증분). 여러 번 지정 가능")
    ap.add_argument("--min-rows", type=int, default=50,
                    help="필터 통과 행이 이 값 이상인 캐릭터만 (기본 50)")
    ap.add_argument("--top-n", type=int, default=30, help="카테고리별 상위 태그 수")
    # ⚠️ 퍼센트 문턱. 이게 없어서 0.5% 태그까지 담겼고, 툴팁에 `purple hair 94%` 옆에
    #    `multicolored hair 3.1%` 가 붙었다(사용자 제보 2026-08-23).
    #
    #    기본값은 **원본에서 역산**했다(추측 아님). 배포본 중 가지치기된 9,673종의
    #    엔트리별 **최저 pct** 분포:
    #      personal_color  p1=30.2% · 30% 미만 14종(0.1%) · 35% 로 올리면 1,393종(14.4%)
    #                      -> 30% 에서 칼같이 갈린다
    #      characteristics 91.7% 가 20% 이상 (색만큼 날카롭지 않다)
    #
    #    두 값 모두 **모든 소비자의 자체 문턱보다 낮다** - 정보 카드 50%,
    #    `build_character_wildcards.py` 40/50, `build_character_presets.mjs` 50.
    #    그래서 화면을 굶기지 않으면서 파일만 정상화한다.
    ap.add_argument("--min-pct-color", type=float, default=30.0,
                    help="personal_color 최소 비율 (기본 30 = 원본 역산값)")
    ap.add_argument("--min-pct-char", type=float, default=20.0,
                    help="characteristics 최소 비율 (기본 20 = 원본 역산값)")
    ap.add_argument("--include-known", action="store_true",
                    help="이미 색인된 캐릭터도 포함(기본은 미색인만)")
    ap.add_argument("--limit-buckets", type=int, default=0,
                    help="앞 N개 버킷만 (시험 실행용). ⚠️ 부분 산출물이 된다")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    classify = load_classification_sets()
    known = known_character_tags()
    print(f"[분류] personal_color {len(classify['personal_color']):,}"
          f" / characteristics {len(classify['characteristics']):,}"
          f" / clothes {len(classify['clothes']):,}")
    print(f"[기존 색인] character_dict_count {len(known):,}종")

    files = bucket_files([Path(c) for c in args.corpus])
    if args.limit_buckets:
        files = files[:args.limit_buckets]
        print(f"⚠️ 시험 실행: 앞 {len(files)}개 버킷만 본다 - 부분 산출물이다")
    print(f"[원천] {len(files)}개 버킷\n")

    cols = ["character", "copyright", "general", "rating"]

    # ── 패스 1: 필터 통과 행 수를 캐릭터별로 센다 ─────────────────────────
    # 자격(>=min_rows)을 먼저 확정해야 패스 2 의 메모리가 유계가 된다.
    row_counts: Counter = Counter()
    total = kept = 0
    for i, path in enumerate(files, 1):
        df = apply_filter(pd.read_parquet(path, columns=cols))
        total += pq.ParquetFile(path).metadata.num_rows
        kept += len(df)
        for value in df["character"]:
            for name in split_names(value):
                row_counts[name] += 1
        if i % 25 == 0 or i == len(files):
            print(f"  [1/2] {i}/{len(files)}  통과 {kept:,}  캐릭터 {len(row_counts):,}",
                  flush=True)

    qualified = {n for n, c in row_counts.items() if c >= args.min_rows}
    targets = qualified if args.include_known else {n for n in qualified
                                                    if n.strip().lower() not in known}
    print(f"\n[필터] {total:,}행 -> {kept:,}행 ({kept/max(1,total)*100:.2f}%)"
          f"  `1girl`∧`solo`∧~alternate∧~cosplay")
    # ⚠️ `targets` 로 미색인 수를 세면 안 된다 - --include-known 이면 전체가 들어와
    #    "자격 N종 중 미색인 N종" 이라는 거짓말이 찍힌다. 항상 `qualified` 로 센다.
    n_new = sum(1 for n in qualified if n.strip().lower() not in known)
    print(f"[자격] {args.min_rows}행 이상: {len(qualified):,}종"
          f"  (미색인 {n_new:,} / 기존 {len(qualified)-n_new:,})")
    print(f"[대상] 이번 실행이 프로필을 만드는 것: {len(targets):,}종"
          + ("  ※ 검산용으로 기존분 포함" if args.include_known else ""))
    if not targets:
        print("대상이 없습니다.")
        return 0

    # ── 패스 2: 대상만 태그를 집계한다 ───────────────────────────────────
    tally: dict[str, Counter] = defaultdict(Counter)
    copyrights: dict[str, Counter] = defaultdict(Counter)
    breast: dict[str, Counter] = defaultdict(Counter)
    rated_rows: Counter = Counter()
    for i, path in enumerate(files, 1):
        df = apply_filter(pd.read_parquet(path, columns=cols))
        for value, cp, general, rating in zip(df["character"], df["copyright"],
                                              df["general"], df["rating"]):
            names = [n for n in split_names(value) if n in targets]
            if not names:
                continue
            tags = [t.strip() for t in str(general or "").split(",") if t.strip()]
            row_breast = BREAST_SET.intersection(tags)
            cp_names = split_names(cp)
            is_sqe = str(rating) in RATINGS_SQE
            for name in names:
                tally[name].update(tags)
                copyrights[name].update(cp_names)
                if is_sqe:
                    rated_rows[name] += 1
                    for bt in row_breast:
                        breast[name][bt] += 1
        if i % 25 == 0 or i == len(files):
            print(f"  [2/2] {i}/{len(files)}", flush=True)

    # ── 조립: character_analysis.json 과 같은 스키마 ─────────────────────
    output: dict[str, dict] = defaultdict(dict)
    for name in sorted(targets, key=lambda n: -row_counts[n]):
        counter = tally.get(name)
        if not counter:
            continue
        rows = row_counts[name]
        entry = {"total_rows": rows, "personal_color": [],
                 "characteristics": [], "key_clothes": []}
        for tag, cnt in counter.most_common():
            pct = round(cnt / rows * 100, 1)
            item = {"tag": tag, "count": cnt, "pct": pct}
            if tag in classify["personal_color"]:
                bucket, floor = entry["personal_color"], args.min_pct_color
            elif tag in classify["clothes"]:
                bucket, floor = entry["key_clothes"], args.min_pct_char
            elif tag in classify["characteristics"]:
                bucket, floor = entry["characteristics"], args.min_pct_char
            else:
                continue
            # ⚠️ 개수 상한만으로는 모자란다. `most_common()` 은 내림차순이라 상한에
            #    걸리기 전까지 **0.5% 짜리도 다 담긴다** - 193행 캐릭터가 색 16개를
            #    달았던 이유다. 문턱을 먼저 본다.
            if pct < floor:
                continue
            if len(bucket) < args.top_n:
                bucket.append(item)
        # 가슴 크기는 characteristics 에서 빼고 별도 필드로 (원본 add_breast_size 규약).
        entry["characteristics"] = [e for e in entry["characteristics"]
                                    if e["tag"] not in BREAST_SET]
        rated = rated_rows.get(name, 0)
        if rated:
            dist = [{"tag": bt, "count": breast[name][bt],
                     "pct": round(breast[name][bt] / rated * 100, 1)}
                    for bt in BREAST_TAGS if breast[name].get(bt)]
            if dist:
                entry["breast_size"] = {"total_rated_rows": rated, "distribution": dist}
        # ⚠️ gender 는 판정하지 않는다. 이 필터가 `1girl` 이라 전원 girl 이 되는데,
        #    그건 기존 데이터의 알려진 오염(남성 캐릭터가 girl 로 들어감)과 같은 함정이다.
        #    값을 모르면 비워 두는 편이 틀린 값을 넣는 것보다 낫다.
        entry["aliases"] = [name]
        group = (copyrights[name].most_common(1) or [("original", 0)])[0][0]
        output[group][name] = entry

    frag = out_dir / "character_analysis_increment.json"
    frag.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    n_chars = sum(len(v) for v in output.values())
    print(f"\n  {frag}  {frag.stat().st_size/1024/1024:.1f} MB"
          f"  ({n_chars:,}종 / 작품 {len(output):,})")

    counts_csv = out_dir / "character_new_counts.csv"
    with counts_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        # `known` 열이 있어야 나중에 신규/기존을 되나눌 수 있다 - 기존분은 산출물
        # 검산용으로만 뽑는 것이라 배포 대상과 섞이면 안 된다.
        fh.write("character,rows,copyright,known\n")
        for name in sorted(targets, key=lambda n: -row_counts[n]):
            group = (copyrights[name].most_common(1) or [("", 0)])[0][0]
            is_known = int(name.strip().lower() in known)
            fh.write(f'"{name}",{row_counts[name]},"{group}",{is_known}\n')
    n_known = sum(1 for n in targets if n.strip().lower() in known)
    print(f"  {counts_csv}   (신규 {len(targets)-n_known:,} / 기존 {n_known:,})")

    print(f"\n=== 상위 15 (표본 순) ===")
    for name in sorted(targets, key=lambda n: -row_counts[n])[:15]:
        group = (copyrights[name].most_common(1) or [("?", 0)])[0][0]
        entry = output.get(group, {}).get(name)
        if not entry:
            continue
        pc = ", ".join(f"{e['tag']} {e['pct']}%" for e in entry["personal_color"][:3])
        ch = ", ".join(f"{e['tag']} {e['pct']}%" for e in entry["characteristics"][:3])
        print(f"  {name}  ({entry['total_rows']}행 · {group})")
        print(f"    색  {pc}")
        print(f"    특징 {ch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
