"""`character` 열 전수조사 — 고유 태그와 빈도.

배포본(`data/tags/tags_000..149`)과 증분 버킷을 각각 세고, 증분에서 **새로 등장한**
캐릭터를 갈라낸다. 태그 문자열은 이미 정규화돼 있으므로(`, ` 결합, 밑줄은 낱말
구분만) 그대로 쓴다.

    python tools/survey_character_tags.py --out <dir> [--inc <buckets dir>]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_DIR = REPO_ROOT / "data" / "tags"

# `hina (blue archive)` 처럼 끝의 괄호가 작품명이다. 없는 것도 많다.
_SERIES = re.compile(r"^(?P<name>.+?)\s*\((?P<series>[^()]*)\)$")


def count_dir(paths: list[Path], label: str) -> tuple[Counter, int, int]:
    """(태그 빈도, 훑은 행 수, character 가 null 인 행 수)."""
    tally: Counter = Counter()
    rows = nulls = 0
    for i, path in enumerate(paths, 1):
        col = pq.read_table(path, columns=["character"]).column("character").to_pylist()
        rows += len(col)
        for value in col:
            if value is None or not str(value).strip():
                nulls += 1
                continue
            for tag in str(value).split(", "):
                if tag:
                    tally[tag] += 1
        if i % 25 == 0 or i == len(paths):
            print(f"  [{label}] {i}/{len(paths)}  누적 고유 {len(tally):,}", flush=True)
    return tally, rows, nulls


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="결과를 쓸 디렉터리")
    ap.add_argument("--inc", default="", help="증분 버킷 디렉터리(없으면 배포본만)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    ship_files = sorted(SHIPPED_DIR.glob("tags_*.parquet"))
    print(f"배포본 {len(ship_files)}개")
    ship, ship_rows, ship_nulls = count_dir(ship_files, "배포본")

    inc: Counter = Counter()
    inc_rows = inc_nulls = 0
    inc_files: list[Path] = []
    if args.inc:
        inc_files = sorted(Path(args.inc).glob("tags_*.parquet"))
        print(f"증분 {len(inc_files)}개")
        inc, inc_rows, inc_nulls = count_dir(inc_files, "증분")

    total = Counter(ship)
    total.update(inc)
    new_only = {t: n for t, n in inc.items() if t not in ship}

    # ---- CSV ------------------------------------------------------------
    csv_path = out_dir / "character_tags.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tag", "name", "series", "count_total",
                    "count_shipped", "count_increment", "is_new"])
        for tag, n in total.most_common():
            m = _SERIES.match(tag)
            w.writerow([tag,
                        m.group("name") if m else tag,
                        m.group("series") if m else "",
                        n, ship.get(tag, 0), inc.get(tag, 0),
                        1 if tag in new_only else 0])

    if new_only:
        new_path = out_dir / "character_tags_new.csv"
        with new_path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["tag", "name", "series", "count_increment"])
            for tag, n in sorted(new_only.items(), key=lambda kv: -kv[1]):
                m = _SERIES.match(tag)
                w.writerow([tag, m.group("name") if m else tag,
                            m.group("series") if m else "", n])

    # ---- 요약 ------------------------------------------------------------
    with_series = sum(1 for t in total if _SERIES.match(t))
    series_tally: Counter = Counter()
    for tag, n in total.items():
        m = _SERIES.match(tag)
        if m:
            series_tally[m.group("series")] += n

    summary = {
        "shipped": {"files": len(ship_files), "rows": ship_rows,
                    "null_rows": ship_nulls, "unique_tags": len(ship),
                    "occurrences": sum(ship.values())},
        "increment": {"files": len(inc_files), "rows": inc_rows,
                      "null_rows": inc_nulls, "unique_tags": len(inc),
                      "occurrences": sum(inc.values())},
        "total_unique": len(total),
        "new_in_increment": len(new_only),
        "tags_with_series": with_series,
        "unique_series": len(series_tally),
    }
    (out_dir / "character_tags_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== 요약 ===")
    print(f"  배포본 : {ship_rows:,}행 · character null {ship_nulls/max(1,ship_rows)*100:.2f}%"
          f" · 고유 {len(ship):,}종 · 출현 {sum(ship.values()):,}회")
    if inc_files:
        print(f"  증분   : {inc_rows:,}행 · character null {inc_nulls/max(1,inc_rows)*100:.2f}%"
              f" · 고유 {len(inc):,}종 · 출현 {sum(inc.values()):,}회")
        print(f"  증분에만 있는 캐릭터: {len(new_only):,}종")
    print(f"  전체 고유: {len(total):,}종  (작품명 괄호 있는 것 {with_series:,}종 /"
          f" 작품 {len(series_tally):,}개)")
    print(f"\n  {csv_path}")
    if new_only:
        print(f"  {out_dir / 'character_tags_new.csv'}")

    print("\n=== 상위 20 ===")
    for tag, n in total.most_common(20):
        print(f"  {n:>9,}  {tag}")
    if new_only:
        print("\n=== 증분 신규 상위 20 ===")
        for tag, n in sorted(new_only.items(), key=lambda kv: -kv[1])[:20]:
            print(f"  {n:>9,}  {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
