"""`build_tag_corpus_increment.py` 의 수집 단계를 **파일 단위로 이어받게** 만든 러너.

왜 따로 두는가
--------------
원본 스크립트는 97개 원격 parquet 을 훑는 동안 결과를 전부 메모리에 쌓아 두었다가
맨 마지막에 한 번에 쓴다. 수 시간짜리 네트워크 작업이라 **중간에 한 번만 끊겨도
그때까지 받은 것을 통째로 잃는다**(실제로 그래서 시험 실행 산출물이 전체 패스로
오인됐다 - 증분이 기대치의 5.8% 였다).

여기서는 파일 하나를 훑을 때마다 그 결과를 staging 에 떨어뜨린다. 다시 돌리면
이미 있는 것은 건너뛴다. 정규화·토큰화·버킷 분할은 **원본 스크립트에서 import** 해
쓰므로 로직이 갈라지지 않는다.

    python tools/fetch_tag_corpus_increment.py fetch --stage <dir>
    python tools/fetch_tag_corpus_increment.py build --stage <dir> --out <dir>
    python tools/fetch_tag_corpus_increment.py status --stage <dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.build_tag_corpus_increment import (  # noqa: E402
    BUCKET_ROWS,
    CLIP_MODEL,
    DEFAULT_DATASET,
    OUT_COLUMNS,
    SRC_COLUMNS,
    TAG_FIELDS,
    existing_state,
    normalize_created_at,
    normalize_tags,
    source_files,
)


def _part_path(stage: Path, index: int) -> Path:
    return stage / f"part_{index:03d}.parquet"


def _done_marker(stage: Path, index: int) -> Path:
    """행이 0건인 파일도 '훑었다' 고 남긴다 - 안 그러면 매번 다시 받는다.

    ⚠️ 앞쪽 파일에는 신규 id 가 아예 없다(실측: 0번 파일 0건). 결과 parquet 이
    없다는 것만으로 미처리로 보면 그 파일들을 영원히 다시 받는다.
    """
    return stage / f"part_{index:03d}.empty"


def cmd_fetch(args) -> int:
    import pandas as pd

    stage = Path(args.stage)
    stage.mkdir(parents=True, exist_ok=True)

    max_id, last_bucket, _buckets = existing_state()
    print(f"[기존] 마지막 id={max_id:,}  마지막 버킷=#{last_bucket}", flush=True)

    files = source_files(args.dataset, None, 0)
    print(f"[원본] {args.dataset}  parquet {len(files)}개", flush=True)

    (stage / "_meta.json").write_text(
        json.dumps({"dataset": args.dataset, "max_id": max_id,
                    "last_bucket": last_bucket, "file_count": len(files)},
                   ensure_ascii=False),
        encoding="utf-8")

    kept = 0
    failed: list[int] = []
    for i, path in enumerate(files):
        part, marker = _part_path(stage, i), _done_marker(stage, i)
        if part.exists() or marker.exists():
            if part.exists():
                kept += len(pd.read_parquet(part, columns=["post_id"]))
            print(f"  [{i + 1}/{len(files)}] 건너뜀(이미 처리)  누적 {kept:,}", flush=True)
            continue
        try:
            df = pd.read_parquet(path, columns=SRC_COLUMNS)
        except Exception as exc:  # noqa: BLE001
            failed.append(i)
            print(f"  [{i + 1}/{len(files)}] 실패 {path}: {exc}", flush=True)
            continue
        df = df[df["post_id"] > max_id]
        if len(df):
            # 원자적으로 쓴다 - 도중에 죽으면 반쪽 파일이 '처리됨' 으로 보인다.
            tmp = part.with_suffix(".parquet.tmp")
            df.to_parquet(tmp, index=False, compression="snappy")
            tmp.replace(part)
            kept += len(df)
        else:
            marker.write_text("0", encoding="utf-8")
        print(f"  [{i + 1}/{len(files)}] +{len(df):,}  누적 {kept:,}", flush=True)

    print(f"\n[수집] 신규 {kept:,}행", flush=True)
    if failed:
        print(f"⚠️ 실패한 파일 {len(failed)}개: {failed}")
        print("   같은 명령을 다시 돌리면 그 파일만 재시도합니다.")
        return 1
    return 0


def cmd_status(args) -> int:
    import pandas as pd

    stage = Path(args.stage)
    meta = json.loads((stage / "_meta.json").read_text(encoding="utf-8"))
    total = int(meta["file_count"])
    done = rows = 0
    for i in range(total):
        part, marker = _part_path(stage, i), _done_marker(stage, i)
        if part.exists():
            done += 1
            rows += len(pd.read_parquet(part, columns=["post_id"]))
        elif marker.exists():
            done += 1
    print(f"진행 {done}/{total} 파일  ({done / total * 100:.1f}%)   누적 신규 {rows:,}행")
    return 0


def cmd_build(args) -> int:
    import pandas as pd

    stage = Path(args.stage)
    meta = json.loads((stage / "_meta.json").read_text(encoding="utf-8"))
    total, last_bucket = int(meta["file_count"]), int(meta["last_bucket"])

    missing = [i for i in range(total)
               if not _part_path(stage, i).exists() and not _done_marker(stage, i).exists()]
    if missing and not args.allow_partial:
        print(f"⚠️ 아직 안 훑은 파일 {len(missing)}개: {missing[:20]}"
              f"{' ...' if len(missing) > 20 else ''}")
        print("   먼저 `fetch` 를 마치거나, 의도한 부분 빌드라면 --allow-partial 을 주세요.")
        return 1
    if missing:
        print(f"⚠️ **부분 빌드**입니다 - 안 훑은 파일 {len(missing)}개.")

    parts = [pd.read_parquet(_part_path(stage, i)) for i in range(total)
             if _part_path(stage, i).exists()]
    if not parts:
        print("[결과] 새로 붙일 행이 없습니다.")
        return 0

    merged = pd.concat(parts, ignore_index=True)
    before = len(merged)
    merged = merged.drop_duplicates(subset=["post_id"]).sort_values("post_id")
    print(f"[정리] {before:,} -> {len(merged):,} (중복 {before - len(merged):,} 제거, id 순 정렬)")

    out = pd.DataFrame({"id": merged["post_id"].astype("int64")})
    for dst, src in TAG_FIELDS.items():
        out[dst] = merged[src].map(normalize_tags)
    out["rating"] = merged["rating"].astype(str)
    out["score"] = merged["score"].fillna(0).astype("int64")
    out["created_at"] = merged["created_at"].map(normalize_created_at)

    print(f"[토큰] CLIP 토크나이저로 general 토큰 수 계산 ({len(out):,}행)", flush=True)
    from transformers import CLIPTokenizerFast

    tok = CLIPTokenizerFast.from_pretrained(CLIP_MODEL)
    texts = out["general"].fillna("").astype(str).tolist()
    counts: list[float] = []
    step = 2000
    for s in range(0, len(texts), step):
        counts.extend(float(len(e)) for e in tok(texts[s:s + step])["input_ids"])
        if (s // step) % 25 == 0:
            print(f"        {min(s + step, len(texts)):,}/{len(texts):,}", flush=True)
    out["tokens"] = counts

    out["image_width"] = merged["image_width"].fillna(0).astype("int64")
    out["image_height"] = merged["image_height"].fillna(0).astype("int64")
    out = out[OUT_COLUMNS]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    new_buckets = []
    for n, start in enumerate(range(0, len(out), BUCKET_ROWS)):
        chunk = out.iloc[start:start + BUCKET_ROWS]
        num = last_bucket + 1 + n
        name = f"tags_{num:03d}.parquet"
        chunk.to_parquet(out_dir / name, index=False, compression="snappy")
        new_buckets.append({
            "bucket": num, "file": name,
            "min_id": int(chunk["id"].iloc[0]), "max_id": int(chunk["id"].iloc[-1]),
            "rows": int(len(chunk)),
            "start_ym": str(chunk["created_at"].iloc[0])[:7].replace("-", "/"),
            "end_ym": str(chunk["created_at"].iloc[-1])[:7].replace("-", "/"),
        })
        print(f"  기록 {name}  {len(chunk):,}행  "
              f"id {chunk['id'].iloc[0]:,}~{chunk['id'].iloc[-1]:,}")

    # ⚠️ 매니페스트는 **출력 디렉터리에** 쓴다. 원본 스크립트는 레포의
    # `data/tag_bucket_dates.json` 을 직접 고쳐서, parquet 은 --out 에 있는데
    # 매니페스트만 레포에 남는 어긋난 상태를 만들었다(유령 버킷 152 가 그 자국).
    (out_dir / "new_buckets.json").write_text(
        json.dumps({"new_buckets": new_buckets, "partial": bool(missing)},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n[완료] 새 버킷 {len(new_buckets)}개 / {len(out):,}행 "
          f"(id {int(out['id'].iloc[0]):,} ~ {int(out['id'].iloc[-1]):,})")
    print(f"       매니페스트 조각: {out_dir / 'new_buckets.json'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="원본을 파일 단위로 훑어 staging 에 저장(이어받기 가능)")
    f.add_argument("--stage", required=True)
    f.add_argument("--dataset", default=DEFAULT_DATASET)
    f.set_defaults(func=cmd_fetch)

    s = sub.add_parser("status", help="진행 상황")
    s.add_argument("--stage", required=True)
    s.set_defaults(func=cmd_status)

    b = sub.add_parser("build", help="staging 을 합쳐 버킷 parquet 생성")
    b.add_argument("--stage", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--allow-partial", action="store_true")
    b.set_defaults(func=cmd_build)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
