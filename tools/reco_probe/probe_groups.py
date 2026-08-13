# -*- coding: utf-8 -*-
"""인원 그룹마다 같은 문턱을 써도 되는가.

사용자 요구는 '모델은 인원 수 별로 맞춰져야 한다' 다. 그룹 규모가 393만~4.8만으로
80배 차이나므로 min_pair 같은 절대 문턱을 공유하면 꼬리 그룹이 통째로 빈다.
그룹별로 지표를 재서 문턱을 규모에 맞춰야 하는지 확인한다.
"""
import math
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(r"C:\VNR\DEV\NAIA2.0")
TRAIN = [ROOT / "data" / "tags" / f"tags_{i}.parquet" for i in range(40, 100)]
HOLD = [ROOT / "data" / "tags" / f"tags_{i}.parquet" for i in (118, 120, 122)]
K_PROMPT, TOP_N, SEED = 3, 8, 20260814
INFO_MAX_P = 0.05
GROUPS = ["1girl_solo", "2girls", "1girl_1boy", "1boy_solo",
          "multiple_girls", "multiple_boys"]


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


def load(paths, want):
    out = defaultdict(list)
    for p in paths:
        for g in pq.read_table(p, columns=["general"]).column("general").to_pylist():
            if not g:
                continue
            s = set(g.split(", "))
            grp = person_group(s)
            if grp in want:
                out[grp].append(s)
    return out


print("적재...", flush=True)
t0 = time.time()
train = load(TRAIN, set(GROUPS))
hold = load(HOLD, set(GROUPS))
print(f"  {time.time()-t0:.0f}s  " +
      " · ".join(f"{g}:{len(train[g]):,}/{len(hold[g]):,}" for g in GROUPS))


class Model:
    def __init__(self, docs, min_freq=20):
        self.freq = Counter()
        for s in docs:
            self.freq.update(s)
        self.vocab = {t: i for i, (t, c) in enumerate(self.freq.most_common())
                      if c >= min_freq}
        self.id_to_tag = {i: t for t, i in self.vocab.items()}
        self.N = max(1, len(docs))
        self.P = {t: self.freq[t] / self.N for t in self.vocab}
        indptr = np.zeros(len(docs) + 1, dtype=np.int64)
        buf = []
        for i, s in enumerate(docs):
            buf.extend(sorted(self.vocab[t] for t in s if t in self.vocab))
            indptr[i + 1] = len(buf)
        self.indptr, self.indices = indptr, np.asarray(buf, dtype=np.int32)
        post_of = np.repeat(np.arange(len(docs), dtype=np.int32), np.diff(indptr))
        order = np.argsort(self.indices, kind="stable")
        self.inv_posts = post_of[order]
        self.bounds = np.searchsorted(self.indices[order],
                                      np.arange(len(self.vocab) + 1))

    def postings(self, t):
        i = self.vocab.get(t)
        return None if i is None else self.inv_posts[self.bounds[i]:self.bounds[i + 1]]

    def _match(self, tags):
        ps = [p for p in (self.postings(t) for t in tags) if p is not None]
        if not ps:
            return None
        ps.sort(key=len)
        cur = ps[0]
        for nxt in ps[1:]:
            cur = np.intersect1d(cur, nxt, assume_unique=True)
        return cur

    def recommend(self, prompt, min_pair, floor, strict_lift=2.0, max_pb=0.30):
        cur = self._match(prompt)
        if cur is None:
            return []
        use = sorted(prompt, key=lambda t: self.freq.get(t, 0))
        while len(cur) < floor and len(use) > 1:
            use.pop(0)
            cur = self._match(use)
            if cur is None:
                return []
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


def evaluate(mdl, cases, min_pair, floor):
    info = {t for t in mdl.vocab if mdl.P[t] <= INFO_MAX_P}
    hit = tot = ihit = empty = 0
    sg = si = 0.0
    for prompt, held in cases:
        r = mdl.recommend(prompt, min_pair, floor)
        if not r:
            empty += 1
        rs = set(r)
        hit += len(rs & held); tot += len(r)
        ihit += len(rs & (held & info))
        sg += sum(-math.log2(mdl.P[t]) for t in rs & held if t in mdl.P)
        si += sum(sorted((-math.log2(mdl.P[t]) for t in held if t in mdl.P),
                         reverse=True)[:TOP_N])
    return (hit / max(tot, 1), ihit / max(tot, 1), sg / max(si, 1e-9),
            empty / max(len(cases), 1))


print(f"\n{'group':<22}{'train':>9}{'min_pair':>9}{'floor':>7}"
      f"{'P@8':>7}{'P@8_info':>10}{'surp':>7}{'빈답%':>7}")
for grp in GROUPS:
    docs = train[grp]
    if len(docs) < 3000:
        print(f"{grp:<22}{len(docs):>9,}   (표본 부족)")
        continue
    mdl = Model(docs)
    rng = random.Random(SEED)
    cs = [s for s in hold[grp] if len(s) >= K_PROMPT + 5]
    rng.shuffle(cs)
    cs = cs[:400]
    cases = []
    for s in cs:
        tg = sorted(s); rng.shuffle(tg)
        cases.append((set(tg[:K_PROMPT]), set(tg[K_PROMPT:])))
    if not cases:
        print(f"{grp:<22}{len(docs):>9,}   (홀드아웃 없음)")
        continue
    # 절대 문턱 vs 규모 비례 문턱
    scale = max(4, int(round(8 * len(docs) / 700_000)))
    for label, mp, fl in (("고정 8/30", 8, 30), (f"비례 {scale}/30", scale, 30)):
        p, pi, sp, em = evaluate(mdl, cases, mp, fl)
        print(f"{grp if label.startswith('고정') else '':<22}"
              f"{len(docs) if label.startswith('고정') else '':>9}"
              f"{label.split()[1]:>9}{fl:>7}{p:>7.3f}{pi:>10.3f}{sp:>7.3f}{em:>7.1%}")
