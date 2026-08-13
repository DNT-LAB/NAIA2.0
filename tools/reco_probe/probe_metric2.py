# -*- coding: utf-8 -*-
"""지표 보정 - 인기도를 빼고 재면 무엇이 이기나.

1차 측정에서 corpus-head 가 precision@8 0.548 을 받았다. 숨긴 태그의 다수가
코퍼스 상위 태그이기 때문이다. 그 지표는 '무용한 답'을 보상한다.

그래서 세 가지로 나눠 잰다:
  P@8        원래대로 (참고용)
  P@8_info   숨긴 태그 중 **흔하지 않은 것**(전역 확률 <= 0.05)만 정답으로 친다
  surprisal  맞힌 태그의 -log2 P(t) 합 / 이상적 합 (nDCG 의 novelty 판)
"""
import math
import random
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(r"C:\VNR\DEV\NAIA2.0")
SHARDS = [ROOT / "data" / "tags" / f"tags_{i}.parquet" for i in range(70, 80)]
HOLDOUT = ROOT / "data" / "tags" / "tags_120.parquet"
K_PROMPT, TOP_N, TRIALS, SEED = 3, 8, 600, 20260814
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


def load(paths, group="1girl_solo"):
    out = []
    for p in paths:
        for g in pq.read_table(p, columns=["general"]).column("general").to_pylist():
            if g:
                s = set(g.split(", "))
                if person_group(s) == group:
                    out.append(s)
    return out


train, hold = load(SHARDS), load([HOLDOUT])
freq = Counter()
for s in train:
    freq.update(s)
vocab = {t: i for i, (t, c) in enumerate(freq.most_common()) if c >= 20}
id_to_tag = {i: t for t, i in vocab.items()}
N = len(train)
P = {t: freq[t] / N for t in vocab}
print(f"train {len(train):,} / holdout {len(hold):,} / vocab {len(vocab):,}")
info_vocab = {t for t in vocab if P[t] <= INFO_MAX_P}
print(f"'정보성' 태그(P<={INFO_MAX_P}): {len(info_vocab):,} / {len(vocab):,}")

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
HEAD = [t for t, _ in freq.most_common(64)]


def postings(t):
    i = vocab.get(t)
    return None if i is None else inv_posts[bounds[i]:bounds[i + 1]]


def _match(prompt):
    ps = [p for p in (postings(t) for t in prompt) if p is not None]
    if not ps:
        return None
    ps.sort(key=len)
    cur = ps[0]
    for nxt in ps[1:]:
        cur = np.intersect1d(cur, nxt, assume_unique=True)
    return cur


def _counts(cur):
    cnt = np.zeros(len(vocab), dtype=np.int32)
    for pi in cur:
        cnt[indices[indptr[pi]:indptr[pi + 1]]] += 1
    return cnt


def rec_head(prompt):
    return [t for t in HEAD if t not in prompt][:TOP_N]


def rec_count(prompt):
    cur = _match(prompt)
    if cur is None or not len(cur):
        return []
    cnt = _counts(cur)
    out = []
    for c in np.argsort(-cnt):
        t = id_to_tag[int(c)]
        if t in prompt:
            continue
        out.append(t)
        if len(out) >= TOP_N:
            break
    return out


def make_lift(strict_lift, max_pb, min_pair=8, backoff=True):
    def fn(prompt):
        cur = _match(prompt)
        if cur is None:
            return []
        # 백오프: 교집합이 너무 작으면 태그를 하나씩 떨어뜨린다(빈도 높은 것부터 유지)
        if backoff:
            ordered = sorted(prompt, key=lambda t: freq.get(t, 0))
            use = list(prompt)
            while len(cur) < 30 and len(use) > 1:
                use.remove(ordered[0]) if ordered[0] in use else None
                ordered.pop(0)
                cur = _match(set(use))
                if cur is None:
                    return []
        if not len(cur):
            return []
        m = len(cur)
        cnt = _counts(cur)
        scored = []
        for c in np.argsort(-cnt)[:800]:
            t = id_to_tag[int(c)]
            if t in prompt or cnt[c] < min_pair:
                continue
            pb = P[t]
            if pb > max_pb:
                continue
            conf = cnt[c] / m
            lift = conf / pb if pb else 0.0
            if lift < strict_lift:
                continue
            scored.append((conf * min(math.log2(max(lift, 1.0)), 3.0), t))
        scored.sort(reverse=True)
        return [t for _, t in scored[:TOP_N]]
    return fn


rng = random.Random(SEED)
cases = [s for s in hold if len(s) >= K_PROMPT + 5]
rng.shuffle(cases)
cases = cases[:TRIALS]
prepared = []
for s in cases:
    tags = sorted(s)
    rng.shuffle(tags)
    prepared.append((set(tags[:K_PROMPT]), set(tags[K_PROMPT:])))

METHODS = [
    ("corpus-head", rec_head),
    ("raw count (Quick Search)", rec_count),
    ("lift>=2.0 P(B)<=0.30", make_lift(2.0, 0.30)),
    ("lift>=1.5 P(B)<=0.50", make_lift(1.5, 0.50)),
    ("lift>=1.2 P(B)<=0.80", make_lift(1.2, 0.80)),
    ("lift>=1.0 P(B)<=1.00", make_lift(1.0, 1.00)),
]
print(f"\n평가 {len(prepared)}건 · 프롬프트 {K_PROMPT} · 상위 {TOP_N}\n")
print(f"{'method':<26}{'P@8':>7}{'P@8_info':>10}{'surprisal':>11}{'빈답':>6}{'ms':>7}")
for name, fn in METHODS:
    hit = tot = 0
    ihit = itot = 0
    sg = si = 0.0
    empty = 0
    t0 = time.time()
    for prompt, held in prepared:
        r = fn(prompt)
        if not r:
            empty += 1
        rs = set(r)
        hit += len(rs & held); tot += len(r)
        held_info = held & info_vocab
        ihit += len(rs & held_info)
        itot += len(r)
        # surprisal: 맞힌 것의 -log2 P 합 / 상위 TOP_N 이상치
        gain = sum(-math.log2(P[t]) for t in rs & held if t in P)
        ideal = sum(sorted((-math.log2(P[t]) for t in held if t in P), reverse=True)[:TOP_N])
        sg += gain; si += ideal
    ms = (time.time() - t0) * 1000 / len(prepared)
    print(f"{name:<26}{hit/max(tot,1):>7.3f}{ihit/max(itot,1):>10.3f}"
          f"{sg/max(si,1e-9):>11.3f}{empty:>6}{ms:>7.1f}")
