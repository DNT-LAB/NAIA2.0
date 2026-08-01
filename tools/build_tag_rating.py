# -*- coding: utf-8 -*-
"""태그별 Danbooru rating 분포 — 성인 판정의 **유일한 근거**.

## 왜 필요한가

성인 도감 빌더들이 이름 정규식으로 성인을 갈랐다(`r"breast|nipple|..."`). 그래서
`hip focus`·`pectoral focus`·`breast focus` 처럼 실제로는 sensitive 가 최빈인 태그가
성인으로 잡혔다. 사용자 지적: **"모든 기준은 Danbooru를 중심으로 해야 한다"**
(2026-08-01). Danbooru 에는 실제 판정(`rating`)이 게시물마다 붙어 있고, 우리 풀에도
그 열이 있다. 추정할 이유가 없다.

실측 예(140만 건):

    sex          explicit 99.7%      pussy       explicit 97.1%
    nude         explicit 73.1%      nipples     explicit 72.6%
    ass focus    explicit 39.1%      breast focus explicit 11.2%
    bikini       explicit  9.2%      long hair   explicit  9.8%

## 기준

`explicit >= 70%` 면 성인(사용자 확정, `nude` 73.1% 를 기준점으로). 이 값은
소비하는 쪽에서 정한다 — 여기서는 분포만 낸다.

표본이 적으면 비율이 튄다(`pectoral focus` 는 22건뿐이다). `n` 을 같이 실으니
소비하는 쪽에서 최소 표본을 걸어라.

사용: python tools/build_tag_rating.py
"""
import json
from pathlib import Path

import pyarrow.parquet as pq

POOL = Path("data/tag_pool_120_139.parquet")
OUT = Path("data/tag_rating.json")
MIN_N = 20          # 이보다 적으면 비율이 의미 없다 — 아예 싣지 않는다


def main() -> int:
    if not POOL.exists():
        raise SystemExit(f"{POOL} 이 없다. tools/build_tag_pool.py 로 먼저 만들어라.")
    counts: dict[str, list[int]] = {}          # 태그 -> [g, s, q, e]
    idx = {"g": 0, "s": 1, "q": 2, "e": 3}
    total = 0
    pf = pq.ParquetFile(POOL)
    for batch in pf.iter_batches(batch_size=50000, columns=["general", "rating"]):
        gens = batch.column("general").to_pylist()
        rats = batch.column("rating").to_pylist()
        for g, r in zip(gens, rats):
            total += 1
            if not g:
                continue
            k = idx.get(str(r or "")[:1].lower())
            if k is None:
                continue
            for t in (str(g).split(", ") if isinstance(g, str) else g):
                row = counts.get(t)
                if row is None:
                    row = counts[t] = [0, 0, 0, 0]
                row[k] += 1

    out = {}
    for t, row in counts.items():
        n = sum(row)
        if n < MIN_N:
            continue
        out[t] = {"n": n, "g": round(row[0] / n * 100, 1), "s": round(row[1] / n * 100, 1),
                  "q": round(row[2] / n * 100, 1), "e": round(row[3] / n * 100, 1)}

    OUT.write_text(json.dumps({
        "note": ["태그별 Danbooru rating 분포(%). tools/build_tag_rating.py 가 만든다.",
                 f"표본 {total:,}건 / 최소 {MIN_N}건 이상인 태그만.",
                 "성인 판정은 이것으로 한다 — 이름 정규식으로 추정하지 않는다.",
                 "g=general s=sensitive q=questionable e=explicit, n=게시물 수."],
        "posts": total, "min_n": MIN_N, "count": len(out), "tags": out,
    }, ensure_ascii=False), encoding="utf-8")
    mb = OUT.stat().st_size / 1024 / 1024
    print(f"게시물 {total:,} / 태그 {len(out):,}개 (n>={MIN_N})")
    print(f"저장: {OUT}  ({mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
