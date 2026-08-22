"""자동완성이 모르는 캐릭터 **전부**(롱테일 포함)의 목록과 희귀 분포.

사용자 지정: 롱테일(사전 하한 20 아래)도 함께 쓴다. 그래서 걸러낸 행 집합은
"자동완성 사전에 없는 캐릭터가 하나라도 든 행" 이고, 여기서는 그 캐릭터들을
희귀도 구간으로 갈라 **무엇이 얼마나 들어 있는지** 보여 준다.

    python tools/character_rarity_report.py --src <buckets> --out <dir>
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_DIR = REPO_ROOT / "data" / "tags"
DICT_FLOOR = 20  # 실측한 자동완성 사전의 빈도 하한(p0=20, <=10 은 0종)

BANDS = [(1, 1), (2, 4), (5, 9), (10, 19), (20, 49), (50, 99),
         (100, 299), (300, 999), (1000, 10 ** 9)]


def autocomplete_characters() -> dict[str, int]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import danbooru_character

    return dict(getattr(danbooru_character, "character_dict_count", {}))


def character_counts(paths: list[Path], label: str) -> Counter:
    tally: Counter = Counter()
    for i, path in enumerate(paths, 1):
        for value in pq.read_table(path, columns=["character"]).column("character").to_pylist():
            if not value:
                continue
            for tag in str(value).split(", "):
                if tag:
                    tally[tag] += 1
        if i % 25 == 0 or i == len(paths):
            print(f"  [{label}] {i}/{len(paths)}", flush=True)
    return tally


def band_of(n: int) -> str:
    for lo, hi in BANDS:
        if lo <= n <= hi:
            return f"{lo}~{hi}" if hi < 10 ** 9 else f"{lo}+"
    return "?"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    known = autocomplete_characters()
    src_files = sorted(Path(args.src).glob("tags_*.parquet"))
    src = character_counts(src_files, "증분")
    ship = character_counts(sorted(SHIPPED_DIR.glob("tags_*.parquet")), "배포본")
    combined = Counter(ship)
    combined.update(src)

    unknown = {t: n for t, n in src.items() if t not in known}
    print(f"\n자동완성이 모르는 캐릭터: {len(unknown):,}종 (증분 출현 {sum(unknown.values()):,}회)")

    # ---- 희귀 분포 -------------------------------------------------------
    print("\n=== 희귀 분포 (증분 출현 기준) ===")
    print(f"  {'구간':>10}  {'캐릭터':>9}  {'출현':>11}  {'25H2 신규':>10}")
    dist_rows = []
    for lo, hi in BANDS:
        sel = [t for t, n in unknown.items() if lo <= n <= hi]
        occ = sum(unknown[t] for t in sel)
        fresh = sum(1 for t in sel if ship.get(t, 0) == 0)
        name = f"{lo}~{hi}" if hi < 10 ** 9 else f"{lo}+"
        print(f"  {name:>10}  {len(sel):>9,}  {occ:>11,}  {fresh:>10,}")
        dist_rows.append([name, len(sel), occ, fresh])

    print("\n=== 코퍼스 전체 빈도 기준(배포본+증분) ===")
    below = sum(1 for t in unknown if combined[t] < DICT_FLOOR)
    print(f"  사전 하한({DICT_FLOOR}) 미만 : {below:,}종  <- 롱테일(이번에 함께 포함)")
    print(f"  하한 이상            : {len(unknown) - below:,}종")
    print(f"  배포본에 아예 없음   : {sum(1 for t in unknown if ship.get(t,0)==0):,}종 (25H2 신규)")

    with (out_dir / "character_rarity_distribution.csv").open(
            "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["band_increment_count", "characters", "occurrences", "new_since_25h2"])
        w.writerows(dist_rows)

    out_csv = out_dir / "characters_unknown_to_autocomplete_all.csv"
    with out_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tag", "count_increment", "count_shipped", "count_combined",
                    "band_increment", "below_dict_floor", "new_since_25h2"])
        for t, n in sorted(unknown.items(), key=lambda kv: -kv[1]):
            w.writerow([t, n, ship.get(t, 0), combined[t], band_of(n),
                        int(combined[t] < DICT_FLOOR), int(ship.get(t, 0) == 0)])

    print(f"\n  {out_dir / 'character_rarity_distribution.csv'}")
    print(f"  {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
