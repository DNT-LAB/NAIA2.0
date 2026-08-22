"""모델 학습 컷오프 **이후 데뷔한 캐릭터**와 그들이 든 행을 뽑는다.

NAI Diffusion V4.5 의 학습 컷오프는 **2025/03**(사용자 확인). 그 뒤에 처음 등장한
캐릭터는 모델이 모른다. 그 캐릭터가 든 행만 모으면 "모델이 못 그리는 캐릭터"
데이터셋이 된다.

⚠️ 데뷔월은 **코퍼스 전체**(배포본 150 + 증분 25 = 175버킷)에서 구해야 한다.
증분(2025-09~)만 보면 2025-04~09 에 데뷔한 캐릭터를 전부 놓치고, 반대로 그 구간에
이미 나왔던 캐릭터를 신규로 잘못 셀 수도 있다.

⚠️ 행 수집은 **컷오프 이후 버킷만** 훑는다. 데뷔가 컷오프 이후면 그 이전 행이
있을 수 없으므로 앞쪽을 읽을 이유가 없다(전체를 읽으면 수 GB 를 헛돈다).

    python tools/build_post_cutoff_character_set.py --inc <buckets> --out <dir> \
        [--cutoff 2025/03]
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


def autocomplete_characters() -> set[str]:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import danbooru_character

    return set(getattr(danbooru_character, "character_dict_count", {}))


def scan_debuts(paths: list[Path], label: str,
                first_ym: dict[str, str], counts: Counter) -> None:
    """`character` 와 `created_at` 만 읽어 첫 등장 월과 빈도를 누적한다."""
    for i, path in enumerate(paths, 1):
        tbl = pq.read_table(path, columns=["character", "created_at"])
        chars = tbl.column("character").to_pylist()
        dates = tbl.column("created_at").to_pylist()
        for value, created in zip(chars, dates):
            if not value or not created:
                continue
            ym = str(created)[:7].replace("-", "/")
            for tag in str(value).split(", "):
                if not tag:
                    continue
                counts[tag] += 1
                prev = first_ym.get(tag)
                if prev is None or ym < prev:
                    first_ym[tag] = ym
        if i % 25 == 0 or i == len(paths):
            print(f"  [{label}] {i}/{len(paths)}  고유 {len(first_ym):,}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inc", required=True, help="증분 버킷 디렉터리")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cutoff", default="2025/03",
                    help="모델 학습 컷오프 YYYY/MM. 이 달 **다음**부터 데뷔한 것을 뽑는다.")
    ap.add_argument("--name", default="", help="산출 parquet 이름(비우면 자동)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cutoff = args.cutoff

    ship_files = sorted(SHIPPED_DIR.glob("tags_*.parquet"))
    inc_files = sorted(Path(args.inc).glob("tags_*.parquet"))
    print(f"배포본 {len(ship_files)} + 증분 {len(inc_files)} = {len(ship_files)+len(inc_files)}버킷")

    first_ym: dict[str, str] = {}
    counts: Counter = Counter()
    scan_debuts(ship_files, "배포본", first_ym, counts)
    scan_debuts(inc_files, "증분", first_ym, counts)
    print(f"\n코퍼스 전체 고유 캐릭터: {len(first_ym):,}종")

    known = autocomplete_characters()
    post = {t: ym for t, ym in first_ym.items() if ym > cutoff}
    print(f"컷오프({cutoff}) 이후 데뷔: {len(post):,}종 (출현 {sum(counts[t] for t in post):,}회)")
    print(f"  그중 자동완성 사전에 있는 것: {sum(1 for t in post if t in known):,}종")

    print("\n=== 데뷔 월 분포 ===")
    by_month = Counter(post.values())
    print(f"  {'월':>9}  {'데뷔':>8}  {'출현':>11}")
    for ym in sorted(by_month):
        occ = sum(counts[t] for t, m in post.items() if m == ym)
        print(f"  {ym:>9}  {by_month[ym]:>8,}  {occ:>11,}")

    # ---- 행 수집: 컷오프 이후 버킷만 -------------------------------------
    manifest_files = []
    for path in ship_files + inc_files:
        end = pq.read_table(path, columns=["created_at"]).column("created_at").to_pylist()
        last = str(end[-1])[:7].replace("-", "/") if end else ""
        if last > cutoff:
            manifest_files.append(path)
    print(f"\n[행 수집] 컷오프 이후 버킷 {len(manifest_files)}개만 훑는다"
          f" (앞쪽 {len(ship_files)+len(inc_files)-len(manifest_files)}개는 읽지 않음)")

    target = set(post)
    kept_frames = []
    scanned = 0
    for i, path in enumerate(manifest_files, 1):
        df = pd.read_parquet(path)
        scanned += len(df)
        ch = df["character"].fillna("")
        mask = ch.map(lambda v: bool(v) and any(t in target for t in str(v).split(", ")))
        if mask.any():
            kept_frames.append(df[mask])
        if i % 5 == 0 or i == len(manifest_files):
            print(f"  {i}/{len(manifest_files)}  남긴 {sum(len(f) for f in kept_frames):,}", flush=True)

    if not kept_frames:
        print("[결과] 남는 행이 없습니다.")
        return 0

    kept = pd.concat(kept_frames, ignore_index=True).sort_values("id", ignore_index=True)
    # 캐릭터 없는 행은 필터 구조상 안 남지만 값으로 확인한다.
    empty = int((kept["character"].fillna("").astype(str).str.strip() == "").sum())
    assert empty == 0, f"character 가 빈 행이 {empty}건 남았다"

    start = cutoff.replace("/", "")[2:]
    end = max(post.values()).replace("/", "")[2:]
    name = args.name or f"naia_{start}_{end}_characters.parquet"
    out_path = out_dir / name
    kept.to_parquet(out_path, index=False, compression="zstd")

    csv_path = out_dir / f"characters_debut_after_{cutoff.replace('/', '')}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tag", "debut_ym", "count_corpus", "in_autocomplete"])
        for tag, ym in sorted(post.items(), key=lambda kv: -counts[kv[0]]):
            w.writerow([tag, ym, counts[tag], int(tag in known)])

    (out_dir / "post_cutoff_summary.json").write_text(json.dumps({
        "cutoff": cutoff, "characters": len(post),
        "buckets_scanned": len(manifest_files), "rows_scanned": scanned,
        "rows_kept": len(kept), "rows_pct": round(len(kept) / max(1, scanned) * 100, 2),
        "output": str(out_path),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n=== 결과 ===")
    print(f"  훑은 행  : {scanned:,}")
    print(f"  남긴 행  : {len(kept):,}  ({len(kept)/max(1,scanned)*100:.2f}%)")
    print(f"  기간     : {kept['created_at'].min()[:10]} ~ {kept['created_at'].max()[:10]}")
    print(f"  크기     : {out_path.stat().st_size/1024/1024:.1f} MB")
    print(f"  rating   : {kept['rating'].value_counts().to_dict()}")
    print(f"  character 빈 행: {empty}")
    print(f"\n  {out_path}")
    print(f"  {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
