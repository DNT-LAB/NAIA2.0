# -*- coding: utf-8 -*-
"""표본추출이 품질을 해치는가 - 메모리 설계를 가르는 실험.

1girl_solo 는 전체 게시물의 52%(393만)이고 혼자 771MB 다. 어휘 문턱으로는 안 줄어든다
(희귀 태그 기여가 0.14%). 남는 수단은 게시물 표본추출뿐이다.

학습 코퍼스를 100/50/25/12.5% 로 줄여 가며 P@N_info 와 surprisal 이 어떻게 되는지 잰다.
평평하면 표본추출이 정답이고, 가파르면 다른 포맷을 찾아야 한다.
"""
import math
import random
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(r"C:\VNR\DEV\NAIA2.0")
TRAIN_SHARDS = [ROOT / "data" / "tags" / f"tags_{i}.parquet" for i in range(60, 90)]
HOLDOUT = ROOT / "data" / "tags" / "tags_120.parquet"
K_PROMPT, TOP_N, TRIALS, SEED = 3, 8, 800, 20260814
INFO_MAX_P = 0.05
FRACTIONS = [1.0, 0.5, 0.25, 0.125, 0.0625]


def person_group(s):
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
        for g in pq.read_table(p, columns=["general"]).column("general").to_pylist():
            if g:
                s = set(g.split(", "))
                if person_group(s) == group:
                    out.append(s)
    return out


print("적재...", flush=True)
t0 = time.time()
full = load(TRAIN_SHARDS)
hold = load([HOLDOUT])
print(f"  train {len(full):,} / holdout {len(hold):,}  ({time.time()-t0:.0f}s)")

rng = random.Random(SEED)
cases = [s for s in hold if len(s) >= K_PROMPT + 5]
rng.shuffle(cases)
cases = cases[:TRIALS]
prepared = []
for s in cases:
    tags = sorted(s)
    rng.shuffle(tags)
    prepared.append((set(tags[:K_PROMPT]), set(tags[K_PROMPT:])))


class Model:
    def __init__(self, docs, min_freq=20):
        self.freq = Counter()
        for s in docs:
            self.freq.update(s)
        self.vocab = {t: i for i, (t, c) in enumerate(self.freq.most_common())
                      if c >= min_freq}
        self.id_to_tag = {i: t for t, i in self.vocab.items()}
        self.N = len(docs)
        self.P = {t: self.freq[t] / self.N for t in self.vocab}
        indptr = np.zeros(len(docs) + 1, dtype=np.int64)
        buf = []
        for i, s in enumerate(docs):
            buf.extend(sorted(self.vocab[t] for t in s if t in self.vocab))
            indptr[i + 1] = len(buf)
        self.indptr = indptr
        self.indices = np.asarray(buf, dtype=np.int32)
        post_of = np.repeat(np.arange(len(docs), dtype=np.int32), np.diff(indptr))
        order = np.argsort(self.indices, kind="stable")
        self.inv_posts = post_of[order]
        self.bounds = np.searchsorted(self.indices[order],
                                      np.arange(len(self.vocab) + 1))
        self.nnz = len(self.indices)

    def postings(self, t):
        i = self.vocab.get(t)
        return None if i is None else self.inv_posts[self.bounds[i]:self.bounds[i + 1]]

    def recommend(self, prompt, strict_lift=2.0, max_pb=0.30, min_pair=8, floor=30):
        ps = [p for p in (self.postings(t) for t in prompt) if p is not None]
        if not ps:
            return []
        ps.sort(key=len)
        cur = ps[0]
        for nxt in ps[1:]:
            cur = np.intersect1d(cur, nxt, assume_unique=True)
        # 백오프 - 희귀 태그부터 떨군다
        use = sorted(prompt, key=lambda t: self.freq.get(t, 0))
        while len(cur) < floor and len(use) > 1:
            use.pop(0)
            ps = [p for p in (self.postings(t) for t in use) if p is not None]
            if not ps:
                return []
            ps.sort(key=len)
            cur = ps[0]
            for nxt in ps[1:]:
                cur = np.intersect1d(cur, nxt, assume_unique=True)
        m = len(cur)
        if not m:
            return []
        cnt = np.zeros(len(self.vocab), dtype=np.int32)
        for pi in cur:
            cnt[self.indices[self.indptr[pi]:self.indptr[pi + 1]]] += 1
        scored = []
        for c in np.argsort(-cnt)[:800]:
            t = self.id_to_tag[int(c)]
            if t in prompt or cnt[c] < min_pair:
                continue
            pb = self.P[t]
            if pb > max_pb:
                continue
            conf = cnt[c] / m
            lift = conf / pb if pb else 0.0
            if lift < strict_lift:
                continue
            scored.append((conf * min(math.log2(max(lift, 1.0)), 3.0), t))
        scored.sort(reverse=True)
        return [t for _, t in scored[:TOP_N]]


print(f"\n{'표본':>8}{'게시물':>10}{'어휘':>8}{'nnz':>12}{'메모리':>9}"
      f"{'P@8':>7}{'P@8_info':>10}{'surprisal':>11}{'빈답':>6}{'ms':>7}")
for frac in FRACTIONS:
    docs = full if frac >= 1.0 else random.Random(SEED).sample(full, int(len(full) * frac))
    mdl = Model(docs)
    info_vocab = {t for t in mdl.vocab if mdl.P[t] <= INFO_MAX_P}
    hit = tot = ihit = itot = empty = 0
    sg = si = 0.0
    t0 = time.time()
    for prompt, held in prepared:
        r = mdl.recommend(prompt)
        if not r:
            empty += 1
        rs = set(r)
        hit += len(rs & held); tot += len(r)
        ihit += len(rs & (held & info_vocab)); itot += len(r)
        sg += sum(-math.log2(mdl.P[t]) for t in rs & held if t in mdl.P)
        si += sum(sorted((-math.log2(mdl.P[t]) for t in held if t in mdl.P),
                         reverse=True)[:TOP_N])
    ms = (time.time() - t0) * 1000 / len(prepared)
    mem = (mdl.nnz * 2 + mdl.nnz * 4 + (len(docs) + 1) * 4) / 1e6
    print(f"{frac:>8.3f}{len(docs):>10,}{len(mdl.vocab):>8,}{mdl.nnz:>12,}"
          f"{mem:>8.0f}M{hit/max(tot,1):>7.3f}{ihit/max(itot,1):>10.3f}"
          f"{sg/max(si,1e-9):>11.3f}{empty:>6}{ms:>7.1f}")
