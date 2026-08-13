# -*- coding: utf-8 -*-
"""평가 지표와 베이스라인 - 독립 측정.

state_system 은 "함수가 뭔가 반환했는가" 를 hit rate 라고 불러서 죽었다(두 축이 100%).
그래서 여기서는 **held-out 예측**으로 잰다.

  게시물의 태그집합 T 에서 k개를 뽑아 프롬프트 P 로 주고, 나머지 H=T\\P 를 숨긴다.
  시스템이 낸 상위 N개 R 에 대해  precision@N = |R∩H| / N.

핵심은 **베이스라인과 비교**하는 것이다. 코퍼스 상위 태그를 그냥 뱉는 것도
0점이 아니다 - 흔한 태그는 실제로 자주 나오기 때문이다. 그 격차가 곧 시스템의 값이다.
"""
import random
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(r"C:\VNR\DEV\NAIA2.0")
SHARDS = [ROOT / "data" / "tags" / f"tags_{i}.parquet" for i in range(70, 80)]
HOLDOUT_SHARD = ROOT / "data" / "tags" / "tags_120.parquet"   # 학습에 안 쓴 시기
K_PROMPT = 3
TOP_N = 8
TRIALS = 600
SEED = 20260814


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


def load(paths, group="1girl_solo"):
    out = []
    for p in paths:
        tb = pq.read_table(p, columns=["general"])
        for g in tb.column("general").to_pylist():
            if not g:
                continue
            s = set(g.split(", "))
            if person_group(s) == group:
                out.append(s)
    return out


print("학습 코퍼스 적재...")
train = load(SHARDS)
print(f"  train {len(train):,}")
hold = load([HOLDOUT_SHARD])
print(f"  holdout {len(hold):,}  (다른 시기 샤드)")

freq = Counter()
for s in train:
    freq.update(s)
MIN_FREQ = 20
vocab = {t: i for i, (t, c) in enumerate(freq.most_common()) if c >= MIN_FREQ}
id_to_tag = {i: t for t, i in vocab.items()}
N = len(train)
print(f"  vocab {len(vocab):,}")

indptr = np.zeros(len(train) + 1, dtype=np.int64)
buf = []
for i, s in enumerate(train):
    buf.extend(sorted(vocab[t] for t in s if t in vocab))
    indptr[i + 1] = len(buf)
indices = np.asarray(buf, dtype=np.int32)
post_of = np.repeat(np.arange(len(train), dtype=np.int32), np.diff(indptr))
order = np.argsort(indices, kind="stable")
inv_posts, inv_tags = post_of[order], indices[order]
bounds = np.searchsorted(inv_tags, np.arange(len(vocab) + 1))

HEAD = [t for t, _ in freq.most_common(TOP_N * 4)]


def postings(t):
    i = vocab.get(t)
    return None if i is None else inv_posts[bounds[i]:bounds[i + 1]]


def rec_head(prompt):
    """베이스라인 1 - 코퍼스 상위 태그. raw-count 점수가 사실상 이것으로 수렴한다."""
    return [t for t in HEAD if t not in prompt][:TOP_N]


def rec_count(prompt):
    """베이스라인 2 - Quick Search 방식: 교집합 후 raw 동시출현 횟수 순."""
    ps = [p for p in (postings(t) for t in prompt) if p is not None]
    if not ps:
        return []
    ps.sort(key=len)
    cur = ps[0]
    for nxt in ps[1:]:
        cur = np.intersect1d(cur, nxt, assume_unique=True)
    if not len(cur):
        return []
    cnt = np.zeros(len(vocab), dtype=np.int32)
    for pi in cur:
        cnt[indices[indptr[pi]:indptr[pi + 1]]] += 1
    out = []
    for c in np.argsort(-cnt):
        t = id_to_tag[int(c)]
        if t in prompt:
            continue
        out.append(t)
        if len(out) >= TOP_N:
            break
    return out


def rec_lift(prompt, min_pair=8, strict_lift=2.0, max_pb=0.30):
    """제안 - 같은 교집합에 conf x min(log2 lift,3) 점수와 게이트."""
    ps = [p for p in (postings(t) for t in prompt) if p is not None]
    if not ps:
        return []
    ps.sort(key=len)
    cur = ps[0]
    for nxt in ps[1:]:
        cur = np.intersect1d(cur, nxt, assume_unique=True)
    m = len(cur)
    if not m:
        return []
    cnt = np.zeros(len(vocab), dtype=np.int32)
    for pi in cur:
        cnt[indices[indptr[pi]:indptr[pi + 1]]] += 1
    scored = []
    for c in np.argsort(-cnt)[:600]:
        t = id_to_tag[int(c)]
        if t in prompt or cnt[c] < min_pair:
            continue
        conf = cnt[c] / m
        pb = freq[t] / N
        if pb > max_pb:
            continue
        lift = conf / pb if pb else 0.0
        if lift < strict_lift:
            continue
        scored.append((conf * min(np.log2(max(lift, 1.0)), 3.0), t))
    scored.sort(reverse=True)
    return [t for _, t in scored[:TOP_N]]


rng = random.Random(SEED)
cases = [s for s in hold if len(s) >= K_PROMPT + 5]
rng.shuffle(cases)
cases = cases[:TRIALS]
print(f"\n평가 {len(cases)}건 · 프롬프트 {K_PROMPT}개 · 상위 {TOP_N}개 예측\n")

METHODS = [("corpus-head (베이스라인)", rec_head),
           ("raw count (Quick Search)", rec_count),
           ("conf x log-lift + 게이트", rec_lift)]
print(f"{'method':<28}{'precision@8':>13}{'recall@8':>10}{'비어있음':>9}{'ms/q':>8}")
for name, fn in METHODS:
    hit = tot = rec_den = rec_hit = empty = 0
    t0 = time.time()
    for s in cases:
        tags = sorted(s)
        rng.shuffle(tags)
        prompt = set(tags[:K_PROMPT])
        held = set(tags[K_PROMPT:])
        r = fn(prompt)
        if not r:
            empty += 1
        hit += len(set(r) & held)
        tot += len(r)
        rec_hit += len(set(r) & held)
        rec_den += min(TOP_N, len(held))
    ms = (time.time() - t0) * 1000 / len(cases)
    print(f"{name:<28}{hit/max(tot,1):>13.3f}{rec_hit/max(rec_den,1):>10.3f}"
          f"{empty:>9}{ms:>8.1f}")
