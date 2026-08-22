""""신규" 아티스트 중 실제로는 **개명/중복해소**인 것을 가려낸다.

Danbooru 아티스트 태그는 개명·동명이인 해소 시 `이름 (구분자)` 로 바뀐다. 그래서
인덱스에 없다고 전부 신규가 아니다. 사용자 제보(2026-08-22)의 두 예시는 **방향이
서로 반대**다:

    yuune (ayanepuna)   <- ayanepuna     괄호 **안**이 옛 이름
    aak (chalie363)     <- aak           괄호 **밖**이 옛 이름

그래서 양쪽을 다 본다. 판정은 이름 모양만으로 하지 않고 **시간 증거**를 붙인다:
옛 이름이 배포본(2025-09 이전)에는 있는데 증분에서 사라졌고 새 이름이 증분에만
있으면 개명이 거의 확실하다. 둘 다 증분에 살아 있으면 별개 작가일 수 있다.

    python tools/detect_artist_renames.py --candidates <csv> --inc <buckets> --out <dir>
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_DIR = REPO_ROOT / "data" / "tags"

# `yuune (ayanepuna)` -> ('yuune', 'ayanepuna'). 중첩 괄호는 다루지 않는다.
_PAREN = re.compile(r"^(?P<base>.+?)\s*\((?P<inner>[^()]+)\)$")


def artist_index() -> dict[str, int]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import artist_dictionary

    return dict(artist_dictionary.artist_dict)


def artist_counts(paths: list[Path], label: str) -> Counter:
    tally: Counter = Counter()
    for i, path in enumerate(paths, 1):
        for value in pq.read_table(path, columns=["artist"]).column("artist").to_pylist():
            if not value:
                continue
            for tag in str(value).split(", "):
                if tag:
                    tally[tag] += 1
        if i % 40 == 0 or i == len(paths):
            print(f"  [{label}] {i}/{len(paths)}  고유 {len(tally):,}", flush=True)
    return tally


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", required=True,
                    help="survey_new_artists 가 낸 *_new_or_rare.csv")
    ap.add_argument("--inc", required=True, help="증분 버킷 디렉터리")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    index = artist_index()
    index_keys = set(index)
    rows = list(csv.DictReader(Path(args.candidates).open(encoding="utf-8-sig")))
    news = [r for r in rows if r.get("status") == "new"]
    print(f"후보 {len(rows):,}종 중 '신규' {len(news):,}종을 검사한다")

    ship = artist_counts(sorted(SHIPPED_DIR.glob("tags_*.parquet")), "배포본")
    inc = artist_counts(sorted(Path(args.inc).glob("tags_*.parquet")), "증분")

    results = []
    for row in news:
        tag = row["artist"].strip()
        m = _PAREN.match(tag)
        if not m:
            results.append((tag, row, "", "", "genuinely_new", ""))
            continue
        base, inner = m.group("base").strip(), m.group("inner").strip()

        # 옛 이름 후보: 괄호 밖(base) 과 괄호 안(inner) 둘 다 본다.
        cands = [c for c in (inner, base) if c in index_keys]
        if not cands:
            results.append((tag, row, base, inner, "genuinely_new", ""))
            continue

        # 시간 증거가 가장 강한 것을 고른다: 배포본에 있고 증분에서 끊긴 이름.
        best, best_kind, best_note = "", "", ""
        for old in cands:
            in_ship, in_inc = ship.get(old, 0), inc.get(old, 0)
            kind = "rename_from_inner" if old == inner else "disambiguated_base"
            if in_ship and not in_inc:
                note = f"옛 이름이 증분에서 사라짐(배포본 {in_ship:,} -> 0)"
                best, best_kind, best_note = old, kind, note
                break                      # 가장 강한 증거 - 더 볼 것 없다
            if not best:
                best, best_kind = old, kind
                best_note = (f"옛 이름이 증분에도 살아 있음(배포본 {in_ship:,} / 증분 {in_inc:,})"
                             if in_inc else f"배포본에도 없음(인덱스 {index.get(old, 0):,})")
        results.append((tag, row, base, inner, best_kind, f"{best} | {best_note}"))

    renamed = [r for r in results if r[4] != "genuinely_new"]
    strong = [r for r in renamed if "사라짐" in r[5]]
    print(f"\n=== 결과 ===")
    print(f"  '신규' {len(news):,}종 중")
    print(f"    개명/중복해소로 보이는 것 : {len(renamed):,}종")
    print(f"      그중 시간 증거까지 일치 : {len(strong):,}종  (옛 이름이 증분에서 끊김)")
    print(f"    진짜 신규                 : {len(news) - len(renamed):,}종")

    by_kind = Counter(r[4] for r in renamed)
    print(f"\n  방향별: {dict(by_kind)}")

    path = out_dir / "artist_rename_candidates.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["artist", "count_src", "base", "inner", "kind", "old_name_evidence"])
        for tag, row, base, inner, kind, note in sorted(
                renamed, key=lambda r: -int(r[1]["count_src"])):
            w.writerow([tag, row["count_src"], base, inner, kind, note])

    genuine = out_dir / "artist_genuinely_new.csv"
    with genuine.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["artist", "count_src"])
        for tag, row, _b, _i, kind, _n in sorted(
                results, key=lambda r: -int(r[1]["count_src"])):
            if kind == "genuinely_new":
                w.writerow([tag, row["count_src"]])

    print(f"\n=== 개명으로 보이는 것 상위 25 ===")
    print(f"  {'출현':>7}  {'방향':<20}  태그 <- 옛 이름")
    for tag, row, _b, _i, kind, note in sorted(
            renamed, key=lambda r: -int(r[1]["count_src"]))[:25]:
        print(f"  {int(row['count_src']):>7,}  {kind:<20}  {tag}  <-  {note}")

    (out_dir / "artist_rename_summary.json").write_text(json.dumps({
        "candidates": len(rows), "checked_new": len(news),
        "renamed": len(renamed), "renamed_with_time_evidence": len(strong),
        "genuinely_new": len(news) - len(renamed), "by_kind": dict(by_kind),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n  {path}")
    print(f"  {genuine}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
