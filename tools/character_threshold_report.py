"""캐릭터 빈도 분포를 보고 **자를 지점**을 고르기 위한 표.

"자동완성에 없는 것 전부" 로 거르면 롱테일 잡음까지 딸려와 행이 33% 나 남았다.
신규 캐릭터는 **자동완성 사전 빈도가 0이거나 아주 낮은데 증분에서는 자주 나오는**
쪽이다. 그 두 축의 분포를 같이 보고 문턱을 정한다.

    python tools/character_threshold_report.py --src <buckets> --out <dir>
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


def row_impact(paths: list[Path], keys: set[str]) -> int:
    """그 캐릭터들이 든 행이 몇 개인가."""
    hit = 0
    for path in paths:
        for value in pq.read_table(path, columns=["character"]).column("character").to_pylist():
            if value and any(t in keys for t in str(value).split(", ")):
                hit += 1
    return hit


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
    total_rows = sum(pq.ParquetFile(p).metadata.num_rows for p in src_files)

    print("\n=== 1) 자동완성 사전 빈도 분포 (47,737종) ===")
    kv = sorted(known.values())
    for q in (0, 5, 10, 25, 50, 75, 90, 100):
        i = min(len(kv) - 1, int(len(kv) * q / 100))
        print(f"  p{q:<3} {kv[i]:>9,}")
    for cut in (1, 5, 10, 20, 50, 100, 200, 500):
        print(f"  빈도 <= {cut:<4} : {sum(1 for v in kv if v <= cut):>7,}종")

    print("\n=== 2) 증분 캐릭터를 사전 빈도로 나눠 보면 ===")
    buckets = {"사전에 없음": [], "1~9": [], "10~49": [], "50~199": [], "200~999": [], "1000+": []}
    for tag, n in src.items():
        k = known.get(tag)
        if k is None:
            buckets["사전에 없음"].append((tag, n))
        elif k < 10:
            buckets["1~9"].append((tag, n))
        elif k < 50:
            buckets["10~49"].append((tag, n))
        elif k < 200:
            buckets["50~199"].append((tag, n))
        elif k < 1000:
            buckets["200~999"].append((tag, n))
        else:
            buckets["1000+"].append((tag, n))
    print(f"  {'사전 빈도':<12} {'캐릭터':>9} {'증분 출현':>12}")
    for label, items in buckets.items():
        print(f"  {label:<12} {len(items):>9,} {sum(n for _, n in items):>12,}")

    print("\n=== 3) 증분에서 자주 나오는데 사전엔 없는 캐릭터 (신규 후보) ===")
    unknown = [(t, n) for t, n in src.items() if t not in known]
    unknown.sort(key=lambda kv: -kv[1])
    print(f"  {'증분 출현':>10}  {'배포본':>8}  태그")
    for t, n in unknown[:25]:
        print(f"  {n:>10,}  {ship.get(t, 0):>8,}  {t}")

    print("\n=== 4) 문턱별 남는 양 (증분 출현 >= N, 사전에 없음) ===")
    print(f"  {'문턱':>6}  {'캐릭터':>9}  {'행':>10}  {'비율':>7}")
    rows = []
    for cut in (1, 3, 5, 10, 20, 50, 100, 300, 1000):
        keys = {t for t, n in unknown if n >= cut}
        hit = row_impact(src_files, keys)
        rows.append((cut, len(keys), hit, hit / max(1, total_rows) * 100))
        print(f"  {cut:>6}  {len(keys):>9,}  {hit:>10,}  {hit/max(1,total_rows)*100:>6.2f}%")

    with (out_dir / "character_threshold_report.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["min_count_in_increment", "characters", "rows_kept", "rows_pct"])
        w.writerows(rows)

    with (out_dir / "new_character_candidates.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tag", "count_increment", "count_shipped", "count_autocomplete"])
        for t, n in unknown:
            w.writerow([t, n, ship.get(t, 0), known.get(t, 0)])

    print(f"\n  {out_dir / 'character_threshold_report.csv'}")
    print(f"  {out_dir / 'new_character_candidates.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
