"""데이터셋을 `1girl` + rating(s/q/e) 로 좁히고, 아티스트별 **평균 score** 를 낸다.

두 단계다:
  1) 필터  general 에 `1girl` 태그가 있고 rating 이 s/q/e 인 행만 남긴다(사이즈 조정).
     ⚠️ `1girl` 은 **온전한 태그**로 찾는다 - 부분문자열로 보면 `1girl` 이 다른 태그의
     조각으로 걸린다. 태그는 `, ` 로 결합돼 있으므로 쪼개서 비교한다.
  2) 집계  주어진 아티스트 목록에 대해 그 부분집합 안에서 score 통계를 낸다.

⚠️ 평균만 내지 않는다. score 는 꼬리가 길어(상위 몇 장이 평균을 끌어올린다) 평균만
보면 한두 장 뜬 작가가 상위에 온다. 중앙값·표본수를 같이 낸다.

    python tools/artist_score_stats.py --src <parquet|buckets dir> \
        --artists <txt|csv> --out <dir> [--keep-parquet]
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

RATINGS = {"s", "q", "e"}
TARGET_TAG = "1girl"


def load_artists(path: Path) -> set[str]:
    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
        key = "artist" if rows and "artist" in rows[0] else list(rows[0])[0]
        return {r[key].strip() for r in rows if r[key].strip()}
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()}


def source_files(src: Path) -> list[Path]:
    if src.is_dir():
        return sorted(src.glob("tags_*.parquet"))
    return [src]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--artists", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-parquet", action="store_true",
                    help="필터 결과를 parquet 으로도 남긴다")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    artists = load_artists(Path(args.artists))
    print(f"[대상 아티스트] {len(artists):,}종")

    files = source_files(Path(args.src))
    print(f"[원본] {len(files)}개 파일")

    scores: dict[str, list[int]] = defaultdict(list)
    kept_frames = []
    total = kept = 0
    for i, path in enumerate(files, 1):
        cols = ["id", "artist", "general", "rating", "score"]
        df = pd.read_parquet(path, columns=cols) if not args.keep_parquet \
            else pd.read_parquet(path)
        total += len(df)

        rating_ok = df["rating"].isin(RATINGS)
        # `1girl` 을 온전한 태그로. 결합자가 `, ` 라 양끝을 감싸 비교하면 정확하다.
        has_1girl = (", " + df["general"].fillna("").astype(str) + ", ").str.contains(
            f", {TARGET_TAG}, ", regex=False)
        sel = df[rating_ok & has_1girl]
        kept += len(sel)
        if args.keep_parquet and len(sel):
            kept_frames.append(sel)

        for art, sc in zip(sel["artist"].fillna(""), sel["score"]):
            if not art:
                continue
            for tag in str(art).split(", "):
                if tag in artists:
                    scores[tag].append(int(sc))
        if i % 5 == 0 or i == len(files):
            print(f"  {i}/{len(files)}  남긴 {kept:,}", flush=True)

    print(f"\n[필터] {total:,}행 -> {kept:,}행 ({kept/max(1,total)*100:.2f}%)"
          f"  `{TARGET_TAG}` + rating {sorted(RATINGS)}")
    print(f"[집계] 대상 아티스트 중 이 부분집합에 등장한 것: {len(scores):,}종"
          f" / {len(artists):,}")

    rows = []
    for tag, values in scores.items():
        values.sort()
        avg = statistics.fmean(values)
        # 표본 1개면 표준편차가 정의되지 않는다 - 0 으로 두고 n 으로 걸러 쓴다.
        sd = statistics.stdev(values) if len(values) > 1 else 0.0
        rows.append({
            "artist": tag,
            "n": len(values),
            "avg_score": round(avg, 2),
            "sd_score": round(sd, 2),
            # 변동계수. 평균이 다른 작가끼리 '들쭉날쭉함' 을 비교하려면 이게 맞다 -
            # 평균 400 에 sd 100 과 평균 10 에 sd 100 은 전혀 다른 이야기다.
            "cv": round(sd / avg, 3) if avg else 0.0,
            "median_score": statistics.median(values),
            "min_score": values[0],
            "max_score": values[-1],
            "p90_score": values[int(len(values) * 0.9)] if len(values) > 1 else values[0],
        })
    rows.sort(key=lambda r: (-r["avg_score"], -r["n"]))

    # ---- 아티스트들이 점수축 어디에 몰려 있는가 ---------------------------
    # ⚠️ score 는 정규분포가 아니다(오른쪽 꼬리가 길다). 평균+-1sd 를 그대로 읽으면
    #    하한이 음수로 내려가 아무 뜻이 없다. 그래서 sd 와 **분위수를 같이** 낸다.
    avgs = sorted(r["avg_score"] for r in rows)
    mean_of_avg = statistics.fmean(avgs)
    sd_of_avg = statistics.stdev(avgs) if len(avgs) > 1 else 0.0
    med_of_avg = statistics.median(avgs)

    def at(pct: float) -> float:
        return avgs[min(len(avgs) - 1, int(len(avgs) * pct / 100))]

    lo1, hi1 = mean_of_avg - sd_of_avg, mean_of_avg + sd_of_avg
    within1 = sum(1 for a in avgs if lo1 <= a <= hi1)
    within2 = sum(1 for a in avgs if abs(a - mean_of_avg) <= 2 * sd_of_avg)
    print(f"\n=== 아티스트 '평균점수' 의 분포 ({len(avgs):,}종) ===")
    print(f"  평균 {mean_of_avg:.1f}   표준편차 {sd_of_avg:.1f}   중앙값 {med_of_avg:.1f}")
    print(f"  +-1sd ({lo1:.1f} ~ {hi1:.1f}) 안: {within1:,}종"
          f" ({within1/len(avgs)*100:.1f}%)   <- 정규분포면 68%")
    print(f"  +-2sd 안: {within2:,}종 ({within2/len(avgs)*100:.1f}%)   <- 정규분포면 95%")
    if lo1 < 0:
        print(f"  ⚠️ 하한이 음수다 - score 는 0 이상이라 정규분포가 아니라는 신호."
              f" 분위수로 읽는 게 맞다.")

    print(f"\n  {'분위':<7}{'평균점수':>10}")
    for q in (5, 10, 25, 50, 75, 90, 95, 99):
        print(f"  p{q:<6}{at(q):>10.1f}")

    print(f"\n  {'구간':>12}  {'아티스트':>9}  {'비율':>7}  {'누적':>7}")
    cum = 0
    for lo, hi in [(0, 5), (5, 10), (10, 20), (20, 40), (40, 80),
                   (80, 160), (160, 10 ** 9)]:
        n_band = sum(1 for a in avgs if lo <= a < hi)
        cum += n_band
        name = f"{lo}~{hi}" if hi < 10 ** 9 else f"{lo}+"
        print(f"  {name:>12}  {n_band:>9,}  {n_band/len(avgs)*100:>6.1f}%"
              f"  {cum/len(avgs)*100:>6.1f}%")

    # ---- 각 아티스트가 얼마나 들쭉날쭉한가 --------------------------------
    # 표본 1~2 장짜리는 sd 가 의미 없다. n>=10 만 본다.
    solid = [r for r in rows if r["n"] >= 10]
    if solid:
        cvs = sorted(r["cv"] for r in solid)
        print(f"\n=== 아티스트 내부 편차 (표본 10장 이상 {len(solid):,}종) ===")
        print(f"  변동계수(sd/평균) 중앙값 {statistics.median(cvs):.2f}"
              f"  p25 {cvs[len(cvs)//4]:.2f}  p75 {cvs[len(cvs)*3//4]:.2f}")
        print(f"  cv < 0.5 (고른 편) : {sum(1 for c in cvs if c < 0.5):,}종")
        print(f"  cv > 1.5 (들쭉날쭉): {sum(1 for c in cvs if c > 1.5):,}종")

    csv_path = out_dir / "artist_score_stats.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["artist"])
        w.writeheader()
        w.writerows(rows)

    if args.keep_parquet and kept_frames:
        merged = pd.concat(kept_frames, ignore_index=True).sort_values("id", ignore_index=True)
        pq_path = out_dir / f"{Path(args.src).stem or 'increment'}_1girl_sqe.parquet"
        merged.to_parquet(pq_path, index=False, compression="zstd")
        print(f"\n  {pq_path}  {pq_path.stat().st_size/1024/1024:.1f} MB / {len(merged):,}행")

    missing = len(artists) - len(scores)
    all_scores = [v for vals in scores.values() for v in vals]
    summary = {
        "artists_requested": len(artists), "artists_present": len(scores),
        "artists_absent": missing,
        "rows_total": total, "rows_kept": kept,
        "filter": {"tag": TARGET_TAG, "ratings": sorted(RATINGS)},
        "overall_avg_score": round(statistics.fmean(all_scores), 2) if all_scores else 0,
        "overall_median_score": statistics.median(all_scores) if all_scores else 0,
    }
    (out_dir / "artist_score_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n전체 평균 score {summary['overall_avg_score']}"
          f" / 중앙값 {summary['overall_median_score']}"
          f"  (이 부분집합에 안 나온 아티스트 {missing:,}종)")

    print(f"\n=== 평균 score 상위 20 (표본 10장 이상) ===")
    print(f"  {'평균':>7}  {'중앙':>6}  {'n':>5}  {'최대':>6}  아티스트")
    for r in [r for r in rows if r["n"] >= 10][:20]:
        print(f"  {r['avg_score']:>7.1f}  {r['median_score']:>6}  {r['n']:>5,}"
              f"  {r['max_score']:>6,}  {r['artist']}")

    print(f"\n=== 표본이 많은 상위 10 ===")
    for r in sorted(rows, key=lambda x: -x["n"])[:10]:
        print(f"  n={r['n']:>5,}  평균 {r['avg_score']:>7.1f}  중앙 {r['median_score']:>5}"
              f"  {r['artist']}")

    print(f"\n  {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
