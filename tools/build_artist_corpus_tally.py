"""코퍼스 전체의 아티스트를 전수 집계한다 (`merge_artist_dictionary_increment.py` 의 입력).

배포본/증분 출현을 따로 유지해 '기존에도 있었나 / 이번에 늘었나' 를 구분할 수 있게 한다.

⚠️ 자동완성 인덱스(`artist_dictionary.artist_dict`)의 빈도는 **옛 스냅샷**이라 실제
   코퍼스 규모와 크게 어긋날 수 있다(실측: `inoino` 인덱스 34 vs 코퍼스 4,353행).
   그래서 "인덱스에 없거나 적다" 를 신규 판정에 쓰면 안 되고, 이 표의 `total` 을 쓴다.

    python tools/build_artist_corpus_tally.py --out <csv> [--corpus <buckets dir>]...
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]


def tally(paths: list[Path], label: str) -> Counter:
    out: Counter = Counter()
    for i, path in enumerate(paths, 1):
        for value in pq.read_table(path, columns=["artist"]).column("artist").to_pylist():
            if not value:
                continue
            for tag in str(value).split(", "):
                if tag:
                    out[tag] += 1
        if i % 50 == 0 or i == len(paths):
            print(f"  [{label}] {i}/{len(paths)}  고유 {len(out):,}", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--corpus", action="append", default=[],
                    help="추가 버킷 디렉터리(증분). 여러 번 지정 가능")
    args = ap.parse_args()

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import artist_dictionary

    index = dict(artist_dictionary.artist_dict)

    ship_files = sorted((REPO_ROOT / "data" / "tags").glob("tags_*.parquet"))
    inc_files: list[Path] = []
    for d in args.corpus:
        inc_files += sorted(Path(d).glob("tags_*.parquet"))
    print(f"배포본 {len(ship_files)}버킷 + 증분 {len(inc_files)}버킷")

    ship = tally(ship_files, "배포본")
    inc = tally(inc_files, "증분") if inc_files else Counter()
    total: Counter = Counter()
    total.update(ship)
    total.update(inc)

    print(f"\n코퍼스 전체 고유 아티스트 {len(total):,}종"
          f"  (배포본 {len(ship):,} / 증분 {len(inc):,})")
    print(f"  증분에서 처음 등장 {len(set(inc) - set(ship)):,}종")
    for thr in (5, 10, 20, 50, 100):
        n = sum(1 for v in total.values() if v > thr)
        print(f"    총 출현 > {thr:<4} {n:>8,}종")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["artist", "total", "shipped", "increment", "index"])
        for tag, n in total.most_common():
            w.writerow([tag, n, ship.get(tag, 0), inc.get(tag, 0), index.get(tag, "")])
    print(f"\n  {out}  {out.stat().st_size/1024/1024:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
