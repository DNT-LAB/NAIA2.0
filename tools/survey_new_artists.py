"""검색 결과 parquet 의 `artist` 를 세고, **내장 아티스트 인덱스와 대조**한다.

목적: "기존에 거의 활동이 없었거나 신규인데, 이번 데이터에서는 제법 나오는" 아티스트를
찾는다. 그런 아티스트는 모델도 자동완성도 모르는 쪽이다.

기본 조건(사용자 지정)
    기존 인덱스 빈도 < 50  (없으면 신규로 본다)
    AND 출현 > 20

⚠️ 내장 인덱스는 `artist_dictionary.py` 의 `artist_dict` 다. 자동완성이 쓰는 것과
같은 원천이라(`core/kr_tag_loader.py` 의 `dict_sources`) 여기가 기준이 된다.

⚠️ **출현을 어디서 세는지가 결과를 크게 바꾼다.** `--corpus` 를 주면 코퍼스
전체(배포본 150 + 증분 25 = 175버킷)에서 세고, 안 주면 `--src` 파일 안에서만 센다.
후보 풀은 어느 쪽이든 `--src` 에 등장한 아티스트다.

    python tools/survey_new_artists.py --src <parquet> --out <dir> \
        [--corpus <increment buckets>] [--index-max 50] [--src-min 20]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]


def artist_index() -> dict[str, int]:
    """내장 아티스트 인덱스 `태그: 빈도`."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import artist_dictionary

    for name in ("artist_dict", "artist_dict_count", "artist_count"):
        value = getattr(artist_dictionary, name, None)
        if isinstance(value, dict) and value:
            print(f"[인덱스] artist_dictionary.{name}  {len(value):,}종")
            return dict(value)
    raise SystemExit("artist_dictionary 에서 아티스트 dict 를 찾지 못했습니다")


def artist_counts(path: Path) -> tuple[Counter, int, int]:
    """(태그 빈도, 행 수, artist 가 빈 행)."""
    tally: Counter = Counter()
    rows = blanks = 0
    for value in pq.read_table(path, columns=["artist"]).column("artist").to_pylist():
        rows += 1
        if not value or not str(value).strip():
            blanks += 1
            continue
        for tag in str(value).split(", "):
            if tag:
                tally[tag] += 1
    return tally, rows, blanks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--corpus", default="",
                    help="증분 버킷 디렉터리. 주면 출현을 **코퍼스 전체**에서 센다")
    ap.add_argument("--index-max", type=int, default=50,
                    help="기존 인덱스 빈도가 이 값 **미만**이면 '거의 활동 없음'")
    ap.add_argument("--src-min", type=int, default=20,
                    help="출현이 이 값 **초과**여야 후보")
    ap.add_argument("--wildcard", default="",
                    help="후보를 와일드카드 txt 로도 쓴다(경로). 기존 파일은 덮지 않는다")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    index = artist_index()
    src = Path(args.src)
    counts, rows, blanks = artist_counts(src)
    print(f"[대상] {src.name}  {rows:,}행 · artist 빈 행 {blanks:,}"
          f" ({blanks/max(1,rows)*100:.1f}%) · 고유 {len(counts):,}종")

    # ---- 코퍼스 전체 빈도(선택) -------------------------------------------
    corpus: Counter = Counter()
    if args.corpus:
        files = sorted((REPO_ROOT / "data" / "tags").glob("tags_*.parquet"))
        files += sorted(Path(args.corpus).glob("tags_*.parquet"))
        print(f"[코퍼스] {len(files)}버킷에서 artist 를 센다", flush=True)
        for i, path in enumerate(files, 1):
            for value in pq.read_table(path, columns=["artist"]).column("artist").to_pylist():
                if not value:
                    continue
                for tag in str(value).split(", "):
                    if tag:
                        corpus[tag] += 1
            if i % 40 == 0 or i == len(files):
                print(f"  {i}/{len(files)}  고유 {len(corpus):,}", flush=True)

    # 조건에 쓰는 빈도. 코퍼스를 안 주면 src 빈도가 그 역할을 한다.
    basis = corpus if args.corpus else counts
    basis_label = "코퍼스 전체" if args.corpus else "src 파일"

    # ---- 정렬된 전체 목록 -------------------------------------------------
    ranked = counts.most_common()
    all_csv = out_dir / f"{src.stem}_artists.csv"
    with all_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["artist", "count_src", "count_corpus", "count_index", "in_index"])
        for tag, n in ranked:
            w.writerow([tag, n, corpus.get(tag, ""), index.get(tag, 0), int(tag in index)])

    # ---- 조건 적용 --------------------------------------------------------
    picked = []
    for tag, n in ranked:
        if basis.get(tag, 0) <= args.src_min:
            continue
        idx = index.get(tag)
        if idx is None or idx < args.index_max:
            picked.append((tag, n, idx))
    # 판정 기준 빈도 순으로 세운다 - 화면에 보이는 순서와 조건이 같아야 읽힌다.
    picked.sort(key=lambda row: -basis.get(row[0], 0))

    new_only = [p for p in picked if p[2] is None]
    low = [p for p in picked if p[2] is not None]

    print(f"\n=== 조건: 인덱스 < {args.index_max} (또는 신규)"
          f" AND {basis_label} 출현 > {args.src_min} ===")
    print(f"  후보 {len(picked):,}종")
    print(f"    인덱스에 아예 없음(신규) : {len(new_only):,}종")
    print(f"    있지만 빈도 < {args.index_max:<4}      : {len(low):,}종")

    csv_path = out_dir / f"{src.stem}_artists_new_or_rare.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["artist", "count_corpus", "count_src", "count_index", "status"])
        for tag, n, idx in picked:
            w.writerow([tag, corpus.get(tag, ""), n, 0 if idx is None else idx,
                        "new" if idx is None else "rare"])

    print(f"\n=== 상위 30 ({basis_label} 빈도 순) ===")
    print(f"  {'코퍼스':>8}  {'src':>6}  {'인덱스':>8}  아티스트")
    for tag, n, idx in picked[:30]:
        cor = corpus.get(tag, 0)
        print(f"  {cor if args.corpus else '-':>8}  {n:>6,}  "
              f"{'신규' if idx is None else format(idx, ',d'):>8}  {tag}")

    (out_dir / f"{src.stem}_artists_summary.json").write_text(json.dumps({
        "source": str(src), "rows": rows, "artist_blank_rows": blanks,
        "unique_artists": len(counts), "index_size": len(index),
        "count_basis": basis_label, "index_max": args.index_max, "src_min": args.src_min,
        "picked": len(picked), "new": len(new_only), "rare": len(low),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n  {all_csv}")
    print(f"  {csv_path}")

    # ---- 와일드카드 txt ---------------------------------------------------
    if args.wildcard:
        wc = Path(args.wildcard)
        if wc.exists():
            # ⚠️ `wildcards/` 는 사용자 데이터다. 절대 덮지 않는다.
            print(f"\n⚠️ 이미 있어 건너뜀(덮지 않음): {wc}")
        else:
            # 괄호는 이스케이프하지 않는다 - 생성 목록의 관례이고
            # `_escape_parens_in_content` 가 최종 포맷에서 처리한다.
            wc.parent.mkdir(parents=True, exist_ok=True)
            wc.write_text("\n".join(t for t, _n, _i in picked) + "\n", encoding="utf-8")
            lines = wc.read_text(encoding="utf-8").splitlines()
            print(f"\n  {wc}  {wc.stat().st_size:,}B / {len(lines):,}줄"
                  f" (빈 줄 {sum(1 for x in lines if not x.strip())})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
