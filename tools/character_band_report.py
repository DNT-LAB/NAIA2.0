"""행 단위 novelty 를 **한 번만 훑어** 모든 문턱을 한꺼번에 답한다.

문턱마다 parquet 을 다시 훑으면 25파일 x N번이다. 대신 행마다 "이 행에 든 캐릭터
중 사전에 없는 것의 최대 빈도" 하나만 뽑아 두면, 임의의 문턱을 그 배열에서 즉시
계산할 수 있다.

⚠️ 자동완성 사전에는 **빈도 하한 20** 이 걸려 있다(실측: p0=20, `<=10` 0종).
그래서 "사전에 없다" 는 곧 "신규" 가 아니라 대부분 **하한 아래 롱테일**이다.
그 둘을 가르려면 코퍼스 전체 빈도(배포본+증분)를 같이 봐야 한다.

    python tools/character_band_report.py --src <buckets> --out <dir>
"""

from __future__ import annotations

import argparse
import bisect
import csv
import sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_DIR = REPO_ROOT / "data" / "tags"
DICT_FLOOR = 20  # 실측한 자동완성 사전의 빈도 하한


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

    unknown = [t for t in src if t not in known]
    below = [t for t in unknown if combined[t] < DICT_FLOOR]
    above = [t for t in unknown if combined[t] >= DICT_FLOOR]
    only_new = [t for t in above if ship.get(t, 0) == 0]

    print(f"\n=== 사전에 없는 {len(unknown):,}종을 코퍼스 전체 빈도로 가르면 ===")
    print(f"  하한({DICT_FLOOR}) 미만 : {len(below):,}종  <- 신규가 아니라 롱테일")
    print(f"  하한 이상      : {len(above):,}종  <- **사전에 들어갔어야 할 것들**")
    print(f"    배포본에 아예 없음: {len(only_new):,}종 (= 25H2 이후 신규)")

    print("\n[스캔] 행마다 '사전에 없는 캐릭터의 최대 증분빈도' 기록", flush=True)
    above_set, new_set = set(above), set(only_new)
    scores: list[int] = []
    scores_new: list[int] = []
    total_rows = 0
    for i, path in enumerate(src_files, 1):
        for value in pq.read_table(path, columns=["character"]).column("character").to_pylist():
            total_rows += 1
            if not value:
                continue
            tags = str(value).split(", ")
            hit = [src[t] for t in tags if t in above_set]
            if hit:
                scores.append(max(hit))
            hit_new = [src[t] for t in tags if t in new_set]
            if hit_new:
                scores_new.append(max(hit_new))
        if i % 5 == 0 or i == len(src_files):
            print(f"  {i}/{len(src_files)}", flush=True)

    scores.sort()
    scores_new.sort()
    print(f"\n총 {total_rows:,}행 중")
    print(f"  '사전에 들어갔어야 할' 캐릭터가 든 행 : {len(scores):>9,}  ({len(scores)/total_rows*100:5.2f}%)")
    print(f"  '25H2 이후 신규' 캐릭터가 든 행       : {len(scores_new):>9,}  ({len(scores_new)/total_rows*100:5.2f}%)")

    BANDS = [(20, 49), (50, 99), (100, 299), (300, 999), (1000, 10 ** 9)]
    rows = []
    for label, arr in (("사전에 들어갔어야 할 것", scores), ("25H2 신규만", scores_new)):
        print(f"\n=== {label} — 캐릭터 증분빈도 구간별 행 수 ===")
        print(f"  {'구간':>12}  {'행':>10}  {'비율':>7}")
        for lo, hi in BANDS:
            n = bisect.bisect_right(arr, hi) - bisect.bisect_left(arr, lo)
            name = f"{lo}~{hi}" if hi < 10 ** 9 else f"{lo}+"
            print(f"  {name:>12}  {n:>10,}  {n/total_rows*100:>6.2f}%")
            rows.append([label, lo, hi if hi < 10 ** 9 else "", n, round(n / total_rows * 100, 2)])
        print(f"  {'합계':>12}  {len(arr):>10,}  {len(arr)/total_rows*100:>6.2f}%")

    with (out_dir / "character_band_report.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["basis", "min_count", "max_count", "rows", "rows_pct"])
        w.writerows(rows)

    with (out_dir / "characters_missing_from_autocomplete.csv").open(
            "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tag", "count_increment", "count_shipped", "count_combined", "is_new_since_25h2"])
        for t in sorted(above, key=lambda x: -src[x]):
            w.writerow([t, src[t], ship.get(t, 0), combined[t], int(ship.get(t, 0) == 0)])

    print(f"\n  {out_dir / 'character_band_report.csv'}")
    print(f"  {out_dir / 'characters_missing_from_autocomplete.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
