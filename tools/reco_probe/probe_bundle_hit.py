# -*- coding: utf-8 -*-
"""반증 실험 8.1 - 조합 완성 지표.

지금까지 쓴 P@N_info 는 개별 태그가 맞으면 점수를 준다. '조합이 맞았는가' 는
증명하지 못한다. 여기서는 크기 3~4 튜플을 내고 통째로 숨긴 태그에 들어가는지 본다.

    ExactBundleHit@K = 1[ 어떤 반환 튜플 B 에 대해 B ⊆ H 이고 B ∩ Q = 공집합 ]

비교 대상 (이걸 못 이기면 설계를 접는다):
  A. 무조건 튜플 헤드 - 코퍼스에서 가장 흔한 튜플을 매번 그대로
  B. 태그를 따로 랭킹해 사후에 4개씩 묶은 것 (조합 모델이 아님)
  C. raw-count 튜플 - lift 없이 빈도만
  D. 제안 - lift 게이트 + 정보량 최대 백오프 + bounded 투영
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
BUNDLE = 3          # 튜플 크기 - 3개가 통째로 맞아야 hit
FLOOR, MIN_PAIR = 30, 6


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
vocab = {t: i for i, (t, c) in enumerate(freq.most_common()) if c >= 20}
id_to_tag = {i: t for t, i in vocab.items()}
N = len(train)
P = {t: freq[t] / N for t in vocab}
SURP = {t: -math.log2(P[t]) for t in vocab}

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
print(f"vocab {len(vocab):,} / nnz {len(indices):,}")


def postings(t):
    i = vocab.get(t)
    return None if i is None else inv_posts[bounds[i]:bounds[i + 1]]


def intersect(tags):
    ps = [p for p in (postings(t) for t in tags) if p is not None]
    if not ps or len(ps) != len(tags):
        return None
    ps.sort(key=len)
    cur = ps[0]
    for nxt in ps[1:]:
        cur = np.intersect1d(cur, nxt, assume_unique=True)
    return cur


def backoff_maxinfo(prompt):
    """정보량 최대 부분집합 - 크기가 큰 것부터, 같은 크기면 surprisal 합이 큰 것."""
    known = [t for t in prompt if t in vocab]
    for size in range(len(known), 0, -1):
        best = None
        for sub in sorted(combinations(known, size),
                          key=lambda c: -sum(SURP.get(t, 0.0) for t in c)):
            cur = intersect(sub)
            if cur is not None and len(cur) >= FLOOR:
                return cur, set(sub)
            if cur is not None and best is None:
                best = (cur, set(sub))
        if size == 1 and best:
            return best
    return None, set(prompt)


def counts_of(cur):
    cnt = np.zeros(len(vocab), dtype=np.int32)
    for pi in cur:
        cnt[indices[indptr[pi]:indptr[pi + 1]]] += 1
    return cnt


# --- 베이스라인 A: 무조건 튜플 헤드 (코퍼스 전체에서 가장 흔한 BUNDLE-튜플) ---
print("무조건 헤드 튜플 계산...", flush=True)
head_tally = Counter()
top_ids = [vocab[t] for t, _ in freq.most_common(60) if t in vocab]
top_set = set(top_ids)
for i in range(0, N, 7):          # 1/7 표본이면 헤드 순위엔 충분
    row = [int(x) for x in indices[indptr[i]:indptr[i + 1]] if x in top_set]
    if len(row) >= BUNDLE:
        for c in combinations(sorted(row)[:8], BUNDLE):
            head_tally[c] += 1
HEAD_TUPLES = [[id_to_tag[c] for c in combo] for combo, _ in head_tally.most_common(40)]
print("  헤드 예:", " / ".join("+".join(t) for t in HEAD_TUPLES[:3]))


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
    cur, used = backoff_maxinfo(prompt)
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
    for combo, n in tally.most_common(60):
        if n < MIN_PAIR:
            break
        out.append([id_to_tag[c] for c in combo])
        if len(out) >= TOP_K:
            break
    return out


def rec_independent(prompt):
    """베이스라인 B - 태그를 따로 랭킹해 사후에 묶는다(조합 모델이 아니다)."""
    cur, used = backoff_maxinfo(prompt)
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
print(f"\n조합 완성 평가 {len(prepared)}건 · 프롬프트 {K_PROMPT} · 튜플 크기 {BUNDLE} "
      f"· 상위 {TOP_K}\n")
print(f"{'method':<24}{'BundleHit@5':>13}{'BundleHit@1':>13}"
      f"{'튜플정밀도':>11}{'빈답':>7}{'ms':>7}")
results = {}
for name, fn in METHODS:
    hit5 = hit1 = 0
    tp = tn = 0
    empty = 0
    per_case = []
    t0 = time.time()
    for prompt, held in prepared:
        r = fn(prompt)
        if not r:
            empty += 1
        ok = [i for i, b in enumerate(r) if set(b) <= held and not (set(b) & prompt)]
        h5 = 1 if ok else 0
        hit5 += h5
        hit1 += 1 if (r and set(r[0]) <= held) else 0
        tp += len(ok); tn += len(r)
        per_case.append(h5)
    ms = (time.time() - t0) * 1000 / len(prepared)
    results[name] = per_case
    print(f"{name:<24}{hit5/len(prepared):>13.3f}{hit1/len(prepared):>13.3f}"
          f"{tp/max(tn,1):>11.3f}{empty:>7}{ms:>7.1f}")

# paired bootstrap - 제안이 최선 베이스라인을 정말로 이기는가
base = max(("A. 무조건 헤드 튜플", "B. 태그 랭킹 후 묶기", "C. raw-count 튜플"),
           key=lambda k: sum(results[k]))
d = [x - y for x, y in zip(results["D. lift 튜플 (제안)"], results[base])]
rb = random.Random(7)
boots = []
for _ in range(2000):
    boots.append(sum(rb.choice(d) for _ in range(len(d))) / len(d))
boots.sort()
lo, hi = boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots))]
print(f"\n최선 베이스라인 = {base}")
print(f"제안 - 베이스라인 차이: {sum(d)/len(d):+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]")
print("판정:", "제안이 유의하게 이긴다" if lo > 0 else
      ("유의하지 않다 - 설계를 재검토하라" if hi > 0 else "제안이 진다 - 멈춰라"))
