# -*- coding: utf-8 -*-
"""반증 실험 8.1 재시도 - 지표를 먼저 고친다.

1차 결과: 제안 0.199 vs raw-count 0.917 -> "멈춰라".
그런데 헤드 튜플이 `1girl + solo + looking at viewer` 였다. 1girl 과 solo 는
**이 그룹의 정의**라 모든 게시물에 있다. 즉 지표가 P@8 과 같은 함정에 빠졌다.

여기서는:
  (1) 진단을 실증한다 - 그룹 내 전역 확률이 1.0 인 태그가 무엇인지 센다
  (2) 지표를 고쳐 다시 잰다 - 번들은 **정보성 태그**(P <= 0.05)로만 구성되어야
      hit 으로 인정한다. 보편 태그로는 점수를 못 얻는다.
  (3) 원래 숫자도 같이 남긴다 - 불리한 결과를 숨기지 않는다
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
BUNDLE, FLOOR, MIN_PAIR = 3, 30, 6
INFO_MAX_P = 0.05


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
    out = []
    for p in paths:
        for g in pq.read_table(p, columns=["general"]).column("general").to_pylist():
            if g:
                s = set(g.split(", "))
                if person_group(s) == GROUP:
                    out.append(s)
    return out


t0 = time.time()
train, hold = load(TRAIN), load(HOLD)
print(f"train {len(train):,} / holdout {len(hold):,}  ({time.time()-t0:.0f}s)")
freq = Counter()
for s in train:
    freq.update(s)
N = len(train)

# (1) 진단
universal = [(t, c / N) for t, c in freq.most_common(12)]
print("\n[진단] 그룹 내 최빈 태그의 전역 확률:")
for t, p in universal:
    mark = "  <- 그룹 정의, 100%" if p > 0.98 else ""
    print(f"   {t:<24}{p:>7.3f}{mark}")

vocab = {t: i for i, (t, c) in enumerate(freq.most_common()) if c >= 20}
id_to_tag = {i: t for t, i in vocab.items()}
P = {t: freq[t] / N for t in vocab}
SURP = {t: -math.log2(P[t]) for t in vocab}
INFO = {t for t in vocab if P[t] <= INFO_MAX_P}
print(f"\n정보성 태그(P<={INFO_MAX_P}): {len(INFO):,} / {len(vocab):,}")

indptr = np.zeros(N + 1, dtype=np.int64)
buf = []
for i, s in enumerate(train):
    buf.extend(sorted(vocab[t] for t in s if t in vocab))
    indptr[i + 1] = len(buf)
indices = np.asarray(buf, dtype=np.int32)
post_of = np.repeat(np.arange(N, dtype=np.int32), np.diff(indptr))
order = np.argsort(indices, kind="stable")
inv_posts = post_of[order]
bounds = np.searchsorted(indices[order], np.arange(len(vocab) + 1))


def postings(t):
    i = vocab.get(t)
    return None if i is None else inv_posts[bounds[i]:bounds[i + 1]]


def intersect(tags):
    ps = [postings(t) for t in tags]
    if any(p is None for p in ps):
        return None
    ps.sort(key=len)
    cur = ps[0]
    for nxt in ps[1:]:
        cur = np.intersect1d(cur, nxt, assume_unique=True)
    return cur


def backoff_maxinfo(prompt):
    known = [t for t in prompt if t in vocab]
    if not known:
        return None, set()
    for size in range(len(known), 0, -1):
        cands = sorted(combinations(known, size),
                       key=lambda c: -sum(SURP.get(t, 0.0) for t in c))
        first = None
        for sub in cands:
            cur = intersect(sub)
            if cur is None:
                continue
            if first is None:
                first = (cur, set(sub))
            if len(cur) >= FLOOR:
                return cur, set(sub)
        if size == 1 and first:
            return first
    return None, set(prompt)


def counts_of(cur):
    cnt = np.zeros(len(vocab), dtype=np.int32)
    for pi in cur:
        cnt[indices[indptr[pi]:indptr[pi + 1]]] += 1
    return cnt


print("무조건 헤드 튜플 계산...", flush=True)
head_tally = Counter()
top_ids = [vocab[t] for t, _ in freq.most_common(60) if t in vocab]
top_set = set(top_ids)
for i in range(0, N, 7):
    row = [int(x) for x in indices[indptr[i]:indptr[i + 1]] if x in top_set]
    if len(row) >= BUNDLE:
        for c in combinations(sorted(row)[:8], BUNDLE):
            head_tally[c] += 1
HEAD_TUPLES = [[id_to_tag[c] for c in combo] for combo, _ in head_tally.most_common(60)]


def rec_head(prompt):
    out = []
    for names in HEAD_TUPLES:
        if set(names) & prompt:
            continue
        out.append(names)
        if len(out) >= TOP_K:
            break
    return out


def rec_tuples(prompt, use_lift):
    cur, _ = backoff_maxinfo(prompt)
    if cur is None or not len(cur):
        return []
    m = len(cur)
    cnt = counts_of(cur)
    keep = np.zeros(len(vocab), dtype=bool)
    for c in np.nonzero(cnt)[0]:
        t = id_to_tag[int(c)]
        if t in prompt or cnt[c] < MIN_PAIR:
            continue
        if use_lift:
            pb = P[t]
            if pb > 0.30 or (cnt[c] / m) / pb < 2.0:
                continue
        keep[c] = True
    tally = Counter()
    for pi in cur:
        row = indices[indptr[pi]:indptr[pi + 1]]
        sel = [int(x) for x in row if keep[x]]
        if len(sel) < BUNDLE:
            continue
        if use_lift:
            sel.sort(key=lambda c: -((cnt[c] / m) / max(P[id_to_tag[c]], 1e-9)))
        else:
            sel.sort(key=lambda c: -cnt[c])
        tally[tuple(sorted(sel[:BUNDLE]))] += 1
    out = []
    for combo, n in tally.most_common(80):
        if n < MIN_PAIR:
            break
        out.append([id_to_tag[c] for c in combo])
        if len(out) >= TOP_K:
            break
    return out


def rec_independent(prompt):
    cur, _ = backoff_maxinfo(prompt)
    if cur is None or not len(cur):
        return []
    m = len(cur)
    cnt = counts_of(cur)
    scored = []
    for c in np.argsort(-cnt)[:400]:
        t = id_to_tag[int(c)]
        if t in prompt or cnt[c] < MIN_PAIR:
            continue
        pb = P[t]
        if pb > 0.30:
            continue
        lift = (cnt[c] / m) / pb
        if lift < 2.0:
            continue
        scored.append((cnt[c] / m * min(math.log2(max(lift, 1.0)), 3.0), t))
    scored.sort(reverse=True)
    tags = [t for _, t in scored[:TOP_K * BUNDLE]]
    return [tags[i:i + BUNDLE] for i in range(0, len(tags), BUNDLE)][:TOP_K]


rng = random.Random(SEED)
cases = [s for s in hold if len(s) >= K_PROMPT + 6]
rng.shuffle(cases)
cases = cases[:TRIALS]
prepared = []
for s in cases:
    tg = sorted(s); rng.shuffle(tg)
    prepared.append((set(tg[:K_PROMPT]), set(tg[K_PROMPT:])))

METHODS = [
    ("A. 무조건 헤드 튜플", rec_head),
    ("B. 태그 랭킹 후 묶기", rec_independent),
    ("C. raw-count 튜플", lambda p: rec_tuples(p, use_lift=False)),
    ("D. lift 튜플 (제안)", lambda p: rec_tuples(p, use_lift=True)),
]
print(f"\n조합 완성 {len(prepared)}건 · 튜플 크기 {BUNDLE} · 상위 {TOP_K}")
print("  Hit    = 아무 튜플이나 통째로 숨긴 태그 안에 (원래 지표)")
print("  Hit_i  = **정보성 태그로만 이뤄진** 튜플이 통째로 들어갔을 때만 인정\n")
print(f"{'method':<24}{'Hit@5':>8}{'Hit_i@5':>10}{'Hit_i@1':>10}"
      f"{'정보튜플율':>11}{'빈답':>6}{'ms':>7}")
res_i = {}
for name, fn in METHODS:
    hit = hi5 = hi1 = 0
    info_t = tot_t = 0
    empty = 0
    per = []
    t0 = time.time()
    for prompt, held in prepared:
        r = fn(prompt)
        if not r:
            empty += 1
        ok = [b for b in r if set(b) <= held and not (set(b) & prompt)]
        oki = [b for b in ok if set(b) <= INFO]
        hit += 1 if ok else 0
        h = 1 if oki else 0
        hi5 += h
        hi1 += 1 if (r and set(r[0]) <= held and set(r[0]) <= INFO) else 0
        info_t += sum(1 for b in r if set(b) <= INFO); tot_t += len(r)
        per.append(h)
    ms = (time.time() - t0) * 1000 / len(prepared)
    res_i[name] = per
    print(f"{name:<24}{hit/len(prepared):>8.3f}{hi5/len(prepared):>10.3f}"
          f"{hi1/len(prepared):>10.3f}{info_t/max(tot_t,1):>11.3f}{empty:>6}{ms:>7.1f}")

base = max(("A. 무조건 헤드 튜플", "B. 태그 랭킹 후 묶기", "C. raw-count 튜플"),
           key=lambda k: sum(res_i[k]))
d = [x - y for x, y in zip(res_i["D. lift 튜플 (제안)"], res_i[base])]
rb = random.Random(7)
boots = sorted(sum(rb.choice(d) for _ in range(len(d))) / len(d) for _ in range(2000))
lo, hi = boots[50], boots[1949]
print(f"\n[정보성 기준] 최선 베이스라인 = {base}")
print(f"제안 - 베이스라인: {sum(d)/len(d):+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]")
print("판정:", "제안이 유의하게 이긴다" if lo > 0 else
      ("유의하지 않다" if hi > 0 else "제안이 진다 - 멈춰라"))
