"""자동완성이 **모르는 캐릭터**가 든 행만 남긴다.

절차
----
1. 대상 parquet 들의 `character` 열에서 `태그: 빈도` 를 센다.
2. 자동완성 원천(`danbooru_character.character_dict_count`, 47,737종)과 대조해
   **사전에 없는 캐릭터**를 뽑는다 = 그 사전이 만들어진 뒤에 추가된 것들.
3. 그 캐릭터가 하나라도 든 행만 남겨 parquet 으로 쓴다.

⚠️ 사전에 없다고 전부 "신규" 는 아니다. 사전에 빈도 하한이 있으면 **옛날부터 있던
희귀 캐릭터**도 빠진다. 그래서 배포본 코퍼스(2025-09 이전)에도 있었는지 함께 표시해
`only_new`(배포본에도 없음 = 진짜 신규)와 `unknown`(사전에만 없음)을 구분한다.

    python tools/filter_new_character_rows.py --src <dir> --out <dir> [--strict]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED_DIR = REPO_ROOT / "data" / "tags"


def autocomplete_characters() -> dict[str, int]:
    """자동완성이 아는 캐릭터 `태그: 빈도`."""
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
            print(f"  [{label}] {i}/{len(paths)}  고유 {len(tally):,}", flush=True)
    return tally


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="거를 대상 parquet 디렉터리(증분 버킷)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--strict", action="store_true",
                    help="배포본 코퍼스에도 없는 캐릭터만 신규로 본다(기본은 사전 기준)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    known = autocomplete_characters()
    known_keys = set(known)
    print(f"자동완성 캐릭터 사전: {len(known_keys):,}종")

    src_files = sorted(Path(args.src).glob("tags_*.parquet"))
    print(f"대상 {len(src_files)}개")
    src_counts = character_counts(src_files, "대상")

    ship_files = sorted(SHIPPED_DIR.glob("tags_*.parquet"))
    print(f"배포본 {len(ship_files)}개 (희귀-옛캐릭터 구분용)")
    ship_counts = character_counts(ship_files, "배포본")
    ship_keys = set(ship_counts)

    unknown = {t: n for t, n in src_counts.items() if t not in known_keys}
    only_new = {t: n for t, n in unknown.items() if t not in ship_keys}
    target = only_new if args.strict else unknown
    target_keys = set(target)

    print(f"\n=== 대조 ===")
    print(f"  대상 고유 캐릭터        : {len(src_counts):,}종")
    print(f"  자동완성에 있는 것      : {len(src_counts) - len(unknown):,}종")
    print(f"  자동완성에 **없는** 것  : {len(unknown):,}종  (출현 {sum(unknown.values()):,}회)")
    print(f"    그중 배포본에도 없음  : {len(only_new):,}종  (= 진짜 신규)")
    print(f"    배포본엔 있던 희귀    : {len(unknown) - len(only_new):,}종")
    print(f"  -> 이번 필터 기준       : {'배포본에도 없음(strict)' if args.strict else '자동완성에 없음'}"
          f"  {len(target_keys):,}종")

    # ---- 캐릭터 목록 CSV --------------------------------------------------
    csv_path = out_dir / ("new_characters_strict.csv" if args.strict else "new_characters.csv")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tag", "count_in_src", "count_in_shipped", "in_shipped"])
        for tag, n in sorted(target.items(), key=lambda kv: -kv[1]):
            w.writerow([tag, n, ship_counts.get(tag, 0), int(tag in ship_keys)])

    # ---- 행 필터 ----------------------------------------------------------
    print("\n[필터] 신규 캐릭터가 든 행만 남긴다", flush=True)
    kept_frames = []
    total_rows = 0
    for i, path in enumerate(src_files, 1):
        df = pd.read_parquet(path)
        total_rows += len(df)
        ch = df["character"].fillna("")
        mask = ch.map(lambda v: any(t in target_keys for t in str(v).split(", ")) if v else False)
        if mask.any():
            kept_frames.append(df[mask])
        if i % 5 == 0 or i == len(src_files):
            kept = sum(len(f) for f in kept_frames)
            print(f"  {i}/{len(src_files)}  남긴 {kept:,}", flush=True)

    if not kept_frames:
        print("[결과] 남는 행이 없습니다.")
        return 0

    kept = pd.concat(kept_frames, ignore_index=True).sort_values("id", ignore_index=True)
    name = "naia_tags_new_characters_strict.parquet" if args.strict else "naia_tags_new_characters.parquet"
    out_path = out_dir / name
    kept.to_parquet(out_path, index=False, compression="zstd")

    summary = {
        "src_files": len(src_files), "src_rows": total_rows,
        "autocomplete_characters": len(known_keys),
        "src_unique_characters": len(src_counts),
        "unknown_to_autocomplete": len(unknown),
        "absent_from_shipped_too": len(only_new),
        "filter_basis": "strict(shipped 에도 없음)" if args.strict else "autocomplete 에 없음",
        "filter_character_count": len(target_keys),
        "kept_rows": len(kept),
        "kept_ratio_pct": round(len(kept) / max(1, total_rows) * 100, 2),
        "output": str(out_path),
    }
    (out_dir / "new_character_filter_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n=== 결과 ===")
    print(f"  대상 행    : {total_rows:,}")
    print(f"  남긴 행    : {len(kept):,}  ({len(kept)/max(1,total_rows)*100:.2f}%)")
    print(f"  기간       : {kept['created_at'].min()[:10]} ~ {kept['created_at'].max()[:10]}")
    print(f"  크기       : {out_path.stat().st_size/1024/1024:.1f} MB")
    print(f"  파일       : {out_path}")
    print(f"  캐릭터 목록: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
