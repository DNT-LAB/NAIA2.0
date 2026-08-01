# -*- coding: utf-8 -*-
"""사전을 **만들 때 쓰지 않은 샤드**로 검증한다.

출처를 풀로 통일하면서 독립 오라클을 잃었다 — 같은 풀로 검증하면 자기 자신을
확인하는 것이라 아무것도 증명하지 못한다. 그래서 다른 시간대 샤드(100~119,
2023~2024)로 같은 간선을 다시 센다.
"""
import json, sys
from collections import Counter
from pathlib import Path
import pyarrow.parquet as pq

co = json.loads(Path("data/tag_cooccurrence.json").read_text(encoding="utf-8"))["companions"]
tg = set(co)
gf = Counter(); pc = Counter(); n = 0
for b in pq.ParquetFile(sys.argv[1]).iter_batches(batch_size=100_000, columns=["general"]):
    for g in b.column(0).to_pylist():
        if not g: continue
        n += 1
        u = {x.strip().lower() for x in str(g).split(",") if x.strip()}
        for t in (u & tg):
            gf[t] += 1
            for c in co[t]:
                if c in u: pc[(t, c)] += 1
edges = tot = 0
for t, cs in co.items():
    if gf.get(t, 0) < 40: continue
    for c in cs:
        tot += 1
        if pc.get((t, c), 0) / gf[t] < 0.005: edges += 1
print(f"홀드아웃 {n:,}게시물 — 판정 가능 간선 {tot:,}")
print(f"  지지 안 함 {edges:,} ({edges/max(tot,1)*100:.2f}%)")
