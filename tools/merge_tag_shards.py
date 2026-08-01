# -*- coding: utf-8 -*-
"""`data/tags/tags_NNN.parquet` 샤드를 하나로 합친다.

## 왜 필요한가

이벤트 코퍼스(`data/quick_search/`, 449만 이벤트)는 어휘가 **16,625개로 선별돼 있다.**
상위 N개가 아니다 — `collared shirt`(27만) · `black headwear`(10.7만) · `two-tone hair`
같은 색 수식어·우산·시점 태그가 통째로 빠져 있고, 그래서 축 태그 215개는 문턱을 어떻게
조절해도 동반 후보를 얻을 수 없다(실측).

`data/tags/` 샤드는 Danbooru 게시물 원본이라 `general` 열에 **전체 어휘**가 들어 있다.
동반 통계의 두 번째 출처로 쓸 수 있다.

## 무엇을 남기는가

`general` · `rating` · `score` 만 남긴다. `artist` · `character` · `copyright` ·
`created_at` 등은 동반 통계에 쓰지 않고, 특히 작가/캐릭터는 후보로 나가면 안 되는 분류다
(`medallion -> oda uri` 같은 오분류의 출처). 열을 버리면 파일도 작아진다.

## 쓰는 법

    python tools/merge_tag_shards.py 120 139
    python tools/merge_tag_shards.py 120 139 -o data/tag_pool_120_139.parquet
"""
import argparse
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

SHARD_DIR = Path("data/tags")
# `character` 는 후보 어휘로 쓰면 안 되지만(`medallion -> oda uri` 같은 오분류의 출처)
# **진단 신호로는 필요하다.** 어떤 동반이 한 캐릭터에서만 나오면 그건 태그 사이의 관계가
# 아니라 그 캐릭터의 디자인이다 — `twintails + horse ears` 가 우마무스메 한 명에서
# 나오는 식이다. 처음엔 이 열을 버렸고, 그래서 `chara` 오분류 187건을 분류로 잡으려다
# 실패했다(후보가 `pink hair` 처럼 평범한 태그라 분류에는 신호가 없다).
KEEP = ["id", "general", "character", "rating", "score"]


def main() -> int:
    ap = argparse.ArgumentParser(description="tags_NNN.parquet 샤드 병합")
    ap.add_argument("start", type=int, help="시작 샤드 번호 (포함)")
    ap.add_argument("end", type=int, help="끝 샤드 번호 (포함)")
    ap.add_argument("-o", "--out", default="", help="출력 경로 (기본 data/tag_pool_<s>_<e>.parquet)")
    args = ap.parse_args()

    out = Path(args.out or f"data/tag_pool_{args.start}_{args.end}.parquet")
    paths = []
    missing = []
    for n in range(args.start, args.end + 1):
        p = SHARD_DIR / f"tags_{n}.parquet"
        (paths if p.exists() else missing).append(p)
    if missing:
        # 조용히 건너뛰면 "왜 표본이 적지" 를 나중에 다시 조사하게 된다.
        print(f"!! 없는 샤드 {len(missing)}개: {[p.name for p in missing]}")
    if not paths:
        raise SystemExit("병합할 샤드가 없다")

    writer = None
    rows = 0
    try:
        for p in paths:
            t = pq.read_table(p, columns=KEEP)
            rows += t.num_rows
            if writer is None:
                writer = pq.ParquetWriter(out, t.schema, compression="zstd")
            else:
                # 스키마가 다르면 조용히 통과시키지 않는다 — 열이 어긋나면 통계가 망가진다.
                if t.schema != writer.schema:
                    raise SystemExit(f"{p.name}: 스키마가 다르다\n{t.schema}\nvs\n{writer.schema}")
            writer.write_table(t)
            print(f"  {p.name:<20}{t.num_rows:>8,}행  (누계 {rows:,})", flush=True)
    finally:
        if writer is not None:
            writer.close()

    size = out.stat().st_size / (1024 * 1024)
    print(f"\n저장: {out}  ({rows:,}행 / {size:.1f} MB / 샤드 {len(paths)}개)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
