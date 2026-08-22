"""캐릭터의 **첫 등장 월**을 구해, 특정 시점 이후 데뷔한 것을 뽑는다.

⚠️ 증분 안에서의 첫 등장만 보면 안 된다. 배포본(2025-09 이전)에 이미 있던 캐릭터는
증분에서 처음 보여도 데뷔가 아니다. 그래서 **배포본에 한 번도 없는 것**만 데뷔로 센다.

    python tools/character_debut_report.py --src <buckets> --out <dir> [--since 2026-05]
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


def shipped_characters() -> set[str]:
    seen: set[str] = set()
    files = sorted(SHIPPED_DIR.glob("tags_*.parquet"))
    for i, path in enumerate(files, 1):
        for value in pq.read_table(path, columns=["character"]).column("character").to_pylist():
            if value:
                seen.update(str(value).split(", "))
        if i % 50 == 0 or i == len(files):
            print(f"  [배포본] {i}/{len(files)}  고유 {len(seen):,}", flush=True)
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--since", default="2026-05", help="이 월(YYYY-MM) 이후 데뷔만")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    known = autocomplete_characters()
    ship = shipped_characters()

    first_ym: dict[str, str] = {}
    counts: Counter = Counter()
    src_files = sorted(Path(args.src).glob("tags_*.parquet"))
    print(f"증분 {len(src_files)}개")
    for i, path in enumerate(src_files, 1):
        tbl = pq.read_table(path, columns=["character", "created_at"])
        chars = tbl.column("character").to_pylist()
        dates = tbl.column("created_at").to_pylist()
        for value, created in zip(chars, dates):
            if not value or not created:
                continue
            ym = str(created)[:7]
            for tag in str(value).split(", "):
                if not tag:
                    continue
                counts[tag] += 1
                prev = first_ym.get(tag)
                if prev is None or ym < prev:
                    first_ym[tag] = ym
        if i % 5 == 0 or i == len(src_files):
            print(f"  [증분] {i}/{len(src_files)}", flush=True)

    # 데뷔 = 배포본에 한 번도 없음
    debut = {t: ym for t, ym in first_ym.items() if t not in ship}
    print(f"\n증분 고유 캐릭터 {len(first_ym):,}종 중 배포본에 없던 것(=데뷔) {len(debut):,}종")

    print("\n=== 데뷔 월 분포 ===")
    by_month = Counter(debut.values())
    print(f"  {'월':>9}  {'데뷔':>8}  {'그중 사전에 없음':>16}")
    for ym in sorted(by_month):
        fresh = sum(1 for t, m in debut.items() if m == ym and t not in known)
        print(f"  {ym:>9}  {by_month[ym]:>8,}  {fresh:>16,}")

    since = args.since
    late = {t: ym for t, ym in debut.items() if ym >= since}
    print(f"\n=== {since} 이후 데뷔: {len(late):,}종 ===")
    ranked = sorted(late.items(), key=lambda kv: -counts[kv[0]])
    print(f"  {'출현':>7}  {'데뷔월':>8}  {'사전':>5}  태그")
    for tag, ym in ranked[:30]:
        print(f"  {counts[tag]:>7,}  {ym:>8}  {'O' if tag in known else 'X':>5}  {tag}")

    path = out_dir / f"character_debut_since_{since.replace('-', '')}.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tag", "first_ym", "count_increment", "in_autocomplete"])
        for tag, ym in ranked:
            w.writerow([tag, ym, counts[tag], int(tag in known)])

    all_path = out_dir / "character_debut_all.csv"
    with all_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tag", "first_ym", "count_increment", "in_autocomplete"])
        for tag, ym in sorted(debut.items(), key=lambda kv: (kv[1], -counts[kv[0]])):
            w.writerow([tag, ym, counts[tag], int(tag in known)])

    print(f"\n  {path}")
    print(f"  {all_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
