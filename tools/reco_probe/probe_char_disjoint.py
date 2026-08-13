# -*- coding: utf-8 -*-
"""반증 실험 8.2 - 캐릭터/작품 분리 분할.

8.1 을 통과했지만, 그 점수가 '의상 호환성' 이 아니라 '캐릭터 의상을 외운 것' 일
수 있다. 같은 캐릭터가 train 과 test 에 동시에 나오면 그 캐릭터의 고정 디자인을
그대로 맞히게 된다(filter_character_bias.py 가 잔여 오분류의 72%를 그것으로 잡았다).

알고리즘은 그대로 두고 **분할만** 바꾼다:
  - 시간 분할 (8.1 과 동일)  vs  캐릭터 분리 분할
  - 캐릭터 분리: test 에 등장하는 캐릭터는 train 에서 통째로 제거

개선폭이 0으로 떨어지면 멈춘다.
"""
import math
import random
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(r"C:\VNR\DEV\NAIA2.0")
TRAIN = [ROOT / "data" / "tags" / f"tags_{i}.parquet" for i in range(60, 90)]
HOLD = [ROOT / "data" / "tags" / f"tags_{i}.parquet" for i in (118, 120, 122)]
GROUP = "1girl_solo"
K_PROMPT, TOP_K, TRIALS, SEED = 3, 5, 800, 20260814
BUNDLE, FLOOR, MIN_PAIR, INFO_MAX_P = 3, 30, 6, 0.05


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


def load(paths):
    """(tags, characters) 를 함께 싣는다."""
    out = []
    for p in paths:
        tb = pq.read_table(p, columns=["general", "character"])
        gs = tb.column("general").to_pylist()
        cs = tb.column("character").to_pylist()
        for g, c in zip(gs, cs):
            if not g:
                continue
            s = set(g.split(", "))
            if person_group(s) == GROUP:
                chars = frozenset(x for x in (c or "").split(", ") if x)
                out.append((s, chars))
    return out


t0 = time.time()
train_all, hold_all = load(TRAIN), load(HOLD)
print(f"train {len(train_all):,} / holdout {len(hold_all):,}  ({time.time()-t0:.0f}s)")
tc = sum(1 for _, c in train_all if c)
print(f"캐릭터 열이 채워진 비율: train {tc/len(train_all):.1%}")

rng = random.Random(SEED)
cases_all = [(s, c) for s, c in hold_all if len(s) >= K_PROMPT + 6]
rng.shuffle(cases_all)
cases_all = cases_all[:TRIALS]
test_chars = set()
for _, c in cases_all:
    test_chars |= c
print(f"평가 {len(cases_all)}건 · 등장 캐릭터 {len(test_chars):,}종")


class Model:
    def __init__(self, docs):
        self.freq = Counter()
        for s in docs:
            self.freq.update(s)
        self.N = max(1, len(docs))
        self.vocab = {t: i for i, (t, c) in enumerate(self.freq.most_common())
                      if c >= 20}
        self.id_to_tag = {i: t for t, i in self.vocab.items()}
        self.P = {t: self.freq[t] / self.N for t in self.vocab}
        self.SURP = {t: -math.log2(self.P[t]) for t in self.vocab}
        self.INFO = {t for t in self.vocab if self.P[t] <= INFO_MAX_P}
        indptr = np.zeros(len(docs) + 1, dtype=np.int64)
        buf = []
        for i, s in enumerate(docs):
            buf.extend(sorted(self.vocab[t] for t in s if t in self.vocab))
            indptr[i + 1] = len(buf)
        self.indptr, self.indices = indptr, np.asarray(buf, dtype=np.int32)
        post_of = np.repeat(np.arange(len(docs), dtype=np.int32), np.diff(indptr))
        order = np.argsort(self.indices, kind="stable")
        self.inv = post_of[order]
        self.bounds = np.searchsorted(self.indices[order],
                                      np.arange(len(self.vocab) + 1))

    def postings(self, t):
        i = self.vocab.get(t)
        return None if i is None else self.inv[self.bounds[i]:self.bounds[i + 1]]

    def _inter(self, tags):
        ps = [self.postings(t) for t in tags]
        if any(p is None for p in ps):
            return None
        ps.sort(key=len)
        cur = ps[0]
        for nxt in ps[1:]:
            cur = np.intersect1d(cur, nxt, assume_unique=True)
        return cur

    def _backoff(self, prompt):
        known = [t for t in prompt if t in self.vocab]
        if not known:
            return None
        for size in range(len(known), 0, -1):
            first = None
            for sub in sorted(combinations(known, size),
                              key=lambda c: -sum(self.SURP.get(t, 0.0) for t in c)):
                cur = self._inter(sub)
                if cur is None:
                    continue
                if first is None:
                    first = cur
                if len(cur) >= FLOOR:
                    return cur
            if size == 1 and first is not None:
                return first
        return None

    def tuples(self, prompt, use_lift=True):
        cur = self._backoff(prompt)
        if cur is None or not len(cur):
            return []
        m = len(cur)
        cnt = np.zeros(len(self.vocab), dtype=np.int32)
        for pi in cur:
            cnt[self.indices[self.indptr[pi]:self.indptr[pi + 1]]] += 1
        keep = np.zeros(len(self.vocab), dtype=bool)
        for c in np.nonzero(cnt)[0]:
            t = self.id_to_tag[int(c)]
            if t in prompt or cnt[c] < MIN_PAIR:
                continue
            if use_lift:
                pb = self.P[t]
                if pb > 0.30 or (cnt[c] / m) / pb < 2.0:
                    continue
            keep[c] = True
        tally = Counter()
        for pi in cur:
            row = self.indices[self.indptr[pi]:self.indptr[pi + 1]]
            sel = [int(x) for x in row if keep[x]]
            if len(sel) < BUNDLE:
                continue
            if use_lift:
                sel.sort(key=lambda c: -((cnt[c] / m)
                                         / max(self.P[self.id_to_tag[c]], 1e-9)))
            else:
                sel.sort(key=lambda c: -cnt[c])
            tally[tuple(sorted(sel[:BUNDLE]))] += 1
        out = []
        for combo, n in tally.most_common(80):
            if n < MIN_PAIR:
                break
            out.append([self.id_to_tag[c] for c in combo])
            if len(out) >= TOP_K:
                break
        return out

    def independent(self, prompt):
        cur = self._backoff(prompt)
        if cur is None or not len(cur):
            return []
        m = len(cur)
        cnt = np.zeros(len(self.vocab), dtype=np.int32)
        for pi in cur:
            cnt[self.indices[self.indptr[pi]:self.indptr[pi + 1]]] += 1
        scored = []
        for c in np.argsort(-cnt)[:400]:
            t = self.id_to_tag[int(c)]
            if t in prompt or cnt[c] < MIN_PAIR:
                continue
            pb = self.P[t]
            if pb > 0.30:
                continue
            lift = (cnt[c] / m) / pb
            if lift < 2.0:
                continue
            scored.append((cnt[c] / m * min(math.log2(max(lift, 1.0)), 3.0), t))
        scored.sort(reverse=True)
        tags = [t for _, t in scored[:TOP_K * BUNDLE]]
        return [tags[i:i + BUNDLE] for i in range(0, len(tags), BUNDLE)][:TOP_K]


def evaluate(mdl, cases):
    out = {}
    for label, fn in (("제안", mdl.tuples), ("베이스라인B", mdl.independent)):
        per = []
        empty = 0
        info_t = tot_t = 0
        for prompt, held in cases:
            r = fn(prompt)
            if not r:
                empty += 1
            ok = [b for b in r if set(b) <= held and not (set(b) & prompt)
                  and set(b) <= mdl.INFO]
            per.append(1 if ok else 0)
            info_t += sum(1 for b in r if set(b) <= mdl.INFO); tot_t += len(r)
        out[label] = (per, empty / len(cases), info_t / max(tot_t, 1))
    return out


prepared = []
for s, c in cases_all:
    tg = sorted(s); rng.shuffle(tg)
    prepared.append((set(tg[:K_PROMPT]), set(tg[K_PROMPT:])))

print("\n[1] 시간 분할 (8.1 과 동일)", flush=True)
m1 = Model([s for s, _ in train_all])
r1 = evaluate(m1, prepared)

print("[2] 캐릭터 분리 분할 - test 캐릭터를 train 에서 제거", flush=True)
kept = [s for s, c in train_all if not (c & test_chars)]
print(f"    train {len(train_all):,} -> {len(kept):,} "
      f"({1-len(kept)/len(train_all):.1%} 제거)")
m2 = Model(kept)
r2 = evaluate(m2, prepared)

print(f"\n{'분할':<16}{'방법':<12}{'Hit_i@5':>10}{'정보튜플율':>11}{'빈답':>8}")
for name, res in (("시간", r1), ("캐릭터 분리", r2)):
    for label, (per, em, it) in res.items():
        print(f"{name:<16}{label:<12}{sum(per)/len(per):>10.3f}{it:>11.3f}{em:>8.1%}")

rb = random.Random(7)
for name, res in (("시간", r1), ("캐릭터 분리", r2)):
    d = [x - y for x, y in zip(res["제안"][0], res["베이스라인B"][0])]
    boots = sorted(sum(rb.choice(d) for _ in range(len(d))) / len(d)
                   for _ in range(2000))
    lo, hi = boots[50], boots[1949]
    print(f"\n[{name}] 제안 - 베이스라인B: {sum(d)/len(d):+.4f} "
          f"95% CI [{lo:+.4f}, {hi:+.4f}]  "
          + ("유의" if lo > 0 else "유의하지 않음"))
