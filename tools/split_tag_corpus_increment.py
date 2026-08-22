"""이미 만들어 둔 **단일 병합 증분 parquet** 을 배포용 버킷으로 나눈다.

`build_tag_corpus_increment.py` 는 수집(HF 데이터셋 스캔, 수십 분)부터 분할까지를
한 번에 한다. 그런데 수집 결과를 병합 파일 하나로 들고 있는 경우(사용자 테스트용
산출물)에는 **수집을 다시 할 이유가 없다** - 분할만 하면 된다. 그 마지막 단계만
떼어낸 것이 이 도구다.

분할 규칙은 빌더와 **같은 상수**(`BUCKET_ROWS`)를 쓴다. 두 곳에 숫자를 적으면
언젠가 갈린다.

⚠️ 배포 전 검산은 행 수가 아니라 **밀도**로 한다(`--check` 가 출력한다). 예전에
`--skip-files` 시험 산출물을 전체 결과로 오인한 적이 있는데, 그때 행 수만 봐서는
구분이 안 됐다. 신규 밀도가 낮으면(기존 id 와 겹치면) 그건 부분 산출물이다.

사용:
  python tools/split_tag_corpus_increment.py <merged.parquet> --out data/tags_increment
  python tools/split_tag_corpus_increment.py <merged.parquet> --out ... --write-index
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.build_tag_corpus_increment import BUCKET_ROWS, OUT_COLUMNS  # noqa: E402

BUCKET_INDEX = REPO_ROOT / "data" / "tag_bucket_dates.json"


def _load_index() -> dict:
    if not BUCKET_INDEX.is_file():
        return {"version": 1, "bucket_count": 0, "buckets": []}
    return json.loads(BUCKET_INDEX.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("merged", help="병합된 증분 parquet")
    ap.add_argument("--out", required=True, help="버킷을 쓸 디렉터리")
    ap.add_argument("--write-index", action="store_true",
                    help="data/tag_bucket_dates.json 에 새 버킷을 이어 붙인다")
    ap.add_argument("--check", action="store_true", help="쓰지 않고 검산만")
    args = ap.parse_args()

    import pandas as pd

    index = _load_index()
    buckets = list(index.get("buckets") or [])
    if not buckets:
        print("[중단] data/tag_bucket_dates.json 에 기존 버킷이 없다 - 이어 붙일 기준이 없다.")
        return 1
    last = buckets[-1]
    last_bucket = int(last["bucket"])
    base_max_id = int(last["max_id"])

    src = Path(args.merged)
    if not src.is_file():
        print(f"[중단] 파일이 없다: {src}")
        return 1

    print(f"[읽기] {src.name}")
    out = pd.read_parquet(src)
    missing = [c for c in OUT_COLUMNS if c not in out.columns]
    if missing:
        print(f"[중단] 열이 모자란다: {missing}")
        return 1
    out = out[OUT_COLUMNS]

    # ---- 검산: 행 수가 아니라 밀도와 겹침 ----
    total = len(out)
    fresh = int((out["id"] > base_max_id).sum())
    density = fresh / total * 100 if total else 0.0
    sorted_ok = bool(out["id"].is_monotonic_increasing)
    print(f"[검산] 행 {total:,} / 기존 최대 id {base_max_id:,}")
    print(f"       신규 밀도 {density:.1f}%  (부분 산출물이면 낮게 나온다)")
    print(f"       id 오름차순 {sorted_ok}")
    if density < 90.0:
        print("[중단] 신규 밀도가 90% 미만이다 - 부분 산출물일 수 있다. 확인 후 다시.")
        return 1
    if not sorted_ok:
        print("[정렬] id 오름차순으로 정렬한다.")
        out = out.sort_values("id").reset_index(drop=True)

    n_buckets = (total + BUCKET_ROWS - 1) // BUCKET_ROWS
    print(f"[계획] {BUCKET_ROWS:,}행씩 -> tags_{last_bucket + 1:03d} ~ "
          f"tags_{last_bucket + n_buckets:03d} ({n_buckets}개)")
    if args.check:
        print("(--check 라 아무것도 쓰지 않았습니다)")
        return 0

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    new_buckets = []
    for n, start in enumerate(range(0, total, BUCKET_ROWS)):
        chunk = out.iloc[start:start + BUCKET_ROWS]
        num = last_bucket + 1 + n
        name = f"tags_{num:03d}.parquet"
        chunk.to_parquet(out_dir / name, index=False, compression="snappy")
        ym = lambda s: str(s)[:7].replace("-", "/")          # noqa: E731
        new_buckets.append({
            "bucket": num, "file": name,
            "min_id": int(chunk["id"].iloc[0]), "max_id": int(chunk["id"].iloc[-1]),
            "rows": int(len(chunk)),
            "start_ym": ym(chunk["created_at"].iloc[0]),
            "end_ym": ym(chunk["created_at"].iloc[-1]),
        })
        print(f"  기록 {name}  {len(chunk):,}행  id {chunk['id'].iloc[0]:,}~{chunk['id'].iloc[-1]:,}")

    index_path = out_dir / "tag_bucket_dates_new_entries.json"
    index_path.write_text(json.dumps(new_buckets, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[인덱스] 새 항목 {len(new_buckets)}개를 {index_path.name} 로 따로 뽑았다.")

    if args.write_index:
        index["buckets"] = buckets + new_buckets
        index["bucket_count"] = len(index["buckets"])
        BUCKET_INDEX.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        print(f"[인덱스] {BUCKET_INDEX.name} 갱신 - 버킷 {index['bucket_count']}개")
    else:
        print("[인덱스] 본 표는 건드리지 않았다(--write-index 로 반영).")

    print()
    print(f"[완료] 버킷 {len(new_buckets)}개 / {total:,}행")
    print("⚠️ TAG_ARCHIVE_EXPECTED_COUNT 는 **올리지 마세요**. 증분을 별도 아카이브로")
    print("   내보낼 것이므로 150 을 그대로 두어야 기존 사용자가 베이스를 다시 받지 않습니다.")
    print("⚠️ 재배포 zip 은 **이름을 바꿔서** 올리세요(다운로더가 바이트 오프셋으로 이어받습니다).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
