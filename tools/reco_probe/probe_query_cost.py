# -*- coding: utf-8 -*-
"""질의 시점 조합 추출이 실현 가능한가 - 독립 측정.

Codex 답변을 검증하기 위한 자체 측정이다. 10샤드로 1girl_solo CSR 을 만들고
(a) 모델 크기, (b) 태그 2~4개 교집합 비용, (c) 매칭 집합에서 조합을 뽑는 비용을 잰다.
"""
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(r"C:\VNR\DEV\NAIA2.0")
SHARDS = [ROOT / "data" / "tags" / f"tags_{i}.parquet" for i in range(70, 80)]

# 인원 판정 - core/preset_input_bridge.py:298-322 의 우선순위 사슬과 같은 규칙
def person_group(s: set) -> str:
    if "multiple girls multiple boys" in s or {"multiple girls", "multiple boys"} <= s:
        return "multiple_girls_multiple_boys"
    if {"1girl", "multiple boys"} <= s:  return "1girl_multiple_boys"
    if {"1boy", "multiple girls"} <= s:  return "1boy_multiple_girls"
    if {"1girl", "1boy"} <= s:           return "1girl_1boy"
    if "2girls" in s:                    return "2girls"
    if "2boys" in s:                     return "2boys"
    if "multiple girls" in s:            return "multiple_girls"
    if "multiple boys" in s:             return "multiple_boys"
    if {"1girl", "solo"} <= s:           return "1girl_solo"
    if {"1boy", "solo"} <= s:            return "1boy_solo"
    if "1girl" in s:                     return "1girl"
    if "1boy" in s:                      return "1boy"
    return "other"


t0 = time.time()
rows, groups = [], Counter()
target = []
for p in SHARDS:
    tb = pq.read_table(p, columns=["general", "rating"])
    gs = tb.column("general").to_pylist()
    rs = tb.column("rating").to_pylist()
    for g, r in zip(gs, rs):
        if not g:
            continue
        s = set(g.split(", "))
        grp = person_group(s)
        groups[grp] += 1
        if grp == "1girl_solo":
            target.append((s, r))
scan = time.time() - t0
print(f"scan {len(SHARDS)} shards: {scan:.1f}s  posts={sum(groups.values()):,}")
print("person groups:", dict(groups.most_common()))
print(f"1girl_solo: {len(target):,}")

# --- 어휘와 CSR ---
t0 = time.time()
freq = Counter()
for s, _ in target:
    freq.update(s)
MIN_FREQ = 20
vocab = {t: i for i, (t, c) in enumerate(freq.most_common()) if c >= MIN_FREQ}
indptr = np.zeros(len(target) + 1, dtype=np.int64)
buf = []
for i, (s, _) in enumerate(target):
    ids = sorted(vocab[t] for t in s if t in vocab)
    buf.extend(ids)
    indptr[i + 1] = len(buf)
indices = np.asarray(buf, dtype=np.int32)
build = time.time() - t0
nnz = len(indices)
print(f"\nvocab(freq>={MIN_FREQ}) {len(vocab):,} / nnz {nnz:,} / build {build:.1f}s")
print(f"CSR bytes: indices {indices.nbytes/1e6:.1f}MB + indptr {indptr.nbytes/1e6:.1f}MB")

# 역인덱스
t0 = time.time()
order = np.argsort(indices, kind="stable")
post_of = np.repeat(np.arange(len(target), dtype=np.int32), np.diff(indptr))
inv_posts = post_of[order]
inv_tags = indices[order]
bounds = np.searchsorted(inv_tags, np.arange(len(vocab) + 1))
inv = time.time() - t0
print(f"inverted index {inv:.1f}s / {inv_posts.nbytes/1e6:.1f}MB")

def postings(tag):
    i = vocab.get(tag)
    if i is None:
        return None
    return inv_posts[bounds[i]:bounds[i + 1]]

id_to_tag = {i: t for t, i in vocab.items()}
N = len(target)

# --- 질의 비용 ---
QUERIES = [
    ["school uniform"],
    ["school uniform", "classroom"],
    ["sword", "armor"],
    ["office lady", "pencil skirt"],
    ["sitting", "indoors", "long hair"],
    ["maid", "apron", "indoors", "smile"],
]
print(f"\n{'query':<46}{'match':>8}{'AND ms':>8}{'combo ms':>10}  top combos")
for q in QUERIES:
    t0 = time.time()
    ps = [postings(t) for t in q]
    if any(p is None for p in ps):
        print(f"{', '.join(q):<46}   (어휘 밖)")
        continue
    ps.sort(key=len)
    cur = ps[0]
    for nxt in ps[1:]:
        cur = np.intersect1d(cur, nxt, assume_unique=True)
    and_ms = (time.time() - t0) * 1000

    # 매칭 집합에서 조합 추출: 태그별 지지도 + 상위 태그 쌍
    t0 = time.time()
    cnt = np.zeros(len(vocab), dtype=np.int32)
    for pi in cur:
        cnt[indices[indptr[pi]:indptr[pi + 1]]] += 1
    m = len(cur)
    qi = {vocab[t] for t in q}
    # lift 로 순위 (배경 태그를 걷어낸다)
    cand = np.argsort(-cnt)[:400]
    scored = []
    for c in cand:
        if c in qi or cnt[c] < 12:
            continue
        conf = cnt[c] / max(m, 1)
        pb = freq[id_to_tag[c]] / N
        lift = conf / pb if pb else 0
        if lift < 2.0 or pb > 0.30:
            continue
        scored.append((conf * min(np.log2(max(lift, 1.0)), 3.0), id_to_tag[c]))
    scored.sort(reverse=True)
    combo_ms = (time.time() - t0) * 1000
    print(f"{', '.join(q):<46}{m:>8,}{and_ms:>8.1f}{combo_ms:>10.1f}  "
          + ", ".join(t for _, t in scored[:6]))

print(f"\n전체 코퍼스 추정 배율: 7,543,144 / {sum(groups.values()):,} = "
      f"{7543144/max(1,sum(groups.values())):.1f}x")
