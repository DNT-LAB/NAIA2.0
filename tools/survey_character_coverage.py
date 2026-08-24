"""자동완성에 없는 캐릭터를 전수 조사한다 — 성별·인원 수를 가리지 않고.

배경: 지금 사전 증분(`build_character_profile_increment.py`)은 `1girl ∧ solo` 로
거른 행만 후보로 삼는다. 그래서 **남성·다인원 캐릭터는 구조적으로 자동완성에
들어올 수 없다.** 사전에 없으면 이름조차 안 뜬다.

    danbooru_character.character_dict_count   빈도  -> 자동완성 노출
    data/character_analysis.json              구성요소 -> 칩 / Copy All

이 도구는 **첫 번째 것**의 격차를 잰다(프로필이 아니라 노출).

## ★ `solo` 인데 캐릭터가 2명 = 대부분 오염이 아니다

실측(tags_100, solo 26,351행 중 4,461행 = 16.93%)에서 표본을 읽어 보면 대부분
**같은 인물의 변형 태깅**이다:

    yuuka (blue archive), yuuka (track) (blue archive)      같은 인물 + 의상
    hifumi (blue archive), hifumi (swimsuit) (blue archive) 같은 인물
    lucia: dawn (punishing...), lucia (punishing...)        같은 인물
    maya (kancolle), shimakaze (kancolle)                   ★ 진짜 다른 두 명

통째로 버리면 의상 변형 캐릭터를 대량으로 잃는다. 그래서 **변형을 접은 뒤**
남는 이름이 2개 이상일 때만 오염으로 본다.

⚠️ 문자열로는 못 접는 것이 있다 — `fukawa toko` / `genocider shou`(같은 인물의
   이중인격) 같은 별칭은 표가 있어야 안다. 이 도구는 그것을 **모른다고 표시**하고
   과잉 배제하지 않는다(오염으로 세되 '문자열로 판정 불가' 로 따로 집계).

    python tools/survey_character_coverage.py --out <dir> [--corpus <buckets dir>]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"

# 인원 수 신호. `solo` 는 "화면에 한 명" 이고 `1girl`/`1boy` 는 그 한 명의 성별이다.
# 실측(tags_100): solo 56.2% · 1girl 67.0% · 1boy 18.5% · 1other 1.9%
PEOPLE_TAGS = ("solo", "solo focus", "1girl", "1boy", "1other",
               "2girls", "2boys", "multiple girls", "multiple boys")

# 괄호 한정자를 떼어 '기본 이름' 을 얻는다.
#   `yuuka (track) (blue archive)` -> `yuuka`
#   `lucia: dawn (punishing: gray raven)` -> `lucia: dawn` -> 콜론 앞 `lucia`
_PAREN = re.compile(r"\s*\([^()]*\)")


def base_name(name: str) -> str:
    """변형을 접기 위한 기본 이름. 괄호를 모두 떼고 콜론 앞만 남긴다."""
    prev = None
    out = str(name or "").strip().lower()
    while prev != out:                      # 중첩 괄호를 반복해서 벗긴다
        prev = out
        out = _PAREN.sub("", out).strip()
    if ":" in out:                          # `lucia: dawn` -> `lucia`
        out = out.split(":", 1)[0].strip()
    return out


def split_names(value: str) -> list[str]:
    return [n.strip() for n in str(value or "").split(", ") if n.strip()]


def distinct_people(names: list[str]) -> int:
    """변형을 접은 뒤 남는 **서로 다른 인물** 수."""
    return len({base_name(n) for n in names if base_name(n)})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--corpus", action="append", default=[],
                    help="추가 버킷 디렉터리(증분). 여러 번 지정 가능")
    ap.add_argument("--min-rows", type=int, default=50,
                    help="보고서에 올릴 최소 깨끗한 행 수 (기본 50)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted((DATA_DIR / "tags").glob("tags_*.parquet"),
                   key=lambda p: int(p.stem.split("_")[1]))
    for d in args.corpus:
        files += sorted(Path(d).glob("tags_*.parquet"),
                        key=lambda p: int(p.stem.split("_")[1]))
    print(f"[원천] {len(files)}개 버킷", flush=True)

    total = Counter()          # 전체 출현 (자동완성 빈도의 잣대)
    clean = Counter()          # 변형을 접었을 때 혼자인 행
    dirty = Counter()          # 다른 인물과 같이 나온 행
    solo_girl = Counter()      # 깨끗한 행 중 1girl
    solo_boy = Counter()       # 깨끗한 행 중 1boy
    solo_other = Counter()     # 깨끗한 행 중 둘 다 아님
    works: dict[str, Counter] = defaultdict(Counter)

    for i, path in enumerate(files, 1):
        df = pd.read_parquet(path, columns=["character", "copyright", "general"])
        general = df["general"].fillna("").astype(str)
        padded = ", " + general + ", "
        has = {t: padded.str.contains(f", {t}, ", regex=False).tolist() for t in ("1girl", "1boy")}
        chars = df["character"].fillna("").astype(str).tolist()
        copys = df["copyright"].fillna("").astype(str).tolist()
        for row_i, value in enumerate(chars):
            names = split_names(value)
            if not names:
                continue
            people = distinct_people(names)
            g, b = has["1girl"][row_i], has["1boy"][row_i]
            work = split_names(copys[row_i])
            for name in names:
                total[name] += 1
                if people <= 1:
                    clean[name] += 1
                    if g and not b:
                        solo_girl[name] += 1
                    elif b and not g:
                        solo_boy[name] += 1
                    else:
                        solo_other[name] += 1
                    for w in work[:1]:
                        works[name][w] += 1
                else:
                    dirty[name] += 1
        if i % 25 == 0 or i == len(files):
            print(f"  [{i}/{len(files)}]  이름 {len(total):,}종", flush=True)

    print(f"\n[코퍼스] 캐릭터 이름 {len(total):,}종")

    # 사전·프로필과 대조
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import danbooru_character  # noqa: E402

    known = {str(k).strip().lower() for k in danbooru_character.character_dict_count}
    analysis = json.loads((DATA_DIR / "character_analysis.json").read_text(encoding="utf-8"))
    have_profile = {str(n).strip().lower()
                    for v in analysis.values() if isinstance(v, dict) for n in v}
    print(f"[사전] {len(known):,}종 / [프로필] {len(have_profile):,}종")

    rows = []
    for name, n_total in total.items():
        key = name.strip().lower()
        n_clean = clean[name]
        if n_clean < args.min_rows:
            continue
        g, b, o = solo_girl[name], solo_boy[name], solo_other[name]
        top_work = works[name].most_common(1)
        rows.append({
            "name": name,
            "work": top_work[0][0] if top_work else "",
            "total": n_total,
            "clean": n_clean,
            "dirty": dirty[name],
            "girl": g, "boy": b, "other": o,
            "gender": "girl" if g > max(b, o) else ("boy" if b > max(g, o) else "other"),
            "in_dict": key in known,
            "has_profile": key in have_profile,
        })
    rows.sort(key=lambda r: -r["clean"])

    missing = [r for r in rows if not r["in_dict"]]
    print(f"\n[자격] 깨끗한 행 {args.min_rows} 이상: {len(rows):,}종")
    print(f"  ★ 사전에 없음(자동완성 불가): {len(missing):,}종")
    by_gender = Counter(r["gender"] for r in missing)
    print("     성별 " + " · ".join(f"{k} {v:,}" for k, v in by_gender.most_common()))
    print(f"  프로필도 없음: {sum(1 for r in rows if not r['has_profile']):,}종")

    print("\n  [사전에 없는 것 — 깨끗한 행 상위 25]")
    for r in missing[:25]:
        print(f"    {r['name'][:38]:<38} {('['+r['work'][:20]+']'):<22} "
              f"clean={r['clean']:<6,} dirty={r['dirty']:<6,} {r['gender']}")

    csv_path = out_dir / "character_coverage.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else
                                ["name", "work", "total", "clean", "dirty",
                                 "girl", "boy", "other", "gender", "in_dict", "has_profile"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n  {csv_path}  ({len(rows):,}행)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
