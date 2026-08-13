# -*- coding: utf-8 -*-
"""조합 내부 중복 제거 - 함의컷 + same_family 를 조합 안에도 건다.

1차 결과의 결함: `sword` -> `holding + weapon + holding weapon + holding sword`.
넷이 서로 함의 관계라 한 칸을 네 번 쓴 셈이다. 기존 노이즈 스택이 이미 푸는 문제인데
(build_tag_cooccurrence.py 의 implication cut 0.95 · same_family) 조합 **내부**에는
안 걸려 있었다.

여기서 검증할 것:
  (a) 중복이 실제로 사라지는가
  (b) 조합의 정보량(surprisal)이 올라가는가
  (c) 비용이 얼마나 늘어나는가
"""
import json
import math
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(r"C:\VNR\DEV\NAIA2.0")
SHARDS = [ROOT / "data" / "tags" / f"tags_{i}.parquet" for i in range(60, 90)]
GROUP = "1girl_solo"
MAIN_GROUPS = {"Clothing_Wear", "Expression_Action", "Location_Background",
               "Food_Object", "NSFW", "Creatures", "Culture_Misc"}
IMPLICATION_CONF = 0.95


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


def same_family(a: str, b: str) -> bool:
    """머리 명사가 같으면 변형이다. build_tag_cooccurrence.py:254-284 와 같은 규칙."""
    if a == b:
        return False
    wa, wb = a.split(), b.split()
    if not wa or not wb:
        return False
    if len(wa) == 1 and len(wb) == 1:
        return False
    return wa[-1] == wb[-1]


raw = json.loads((ROOT / "data" / "interactive_tags.json").read_text(encoding="utf-8"))
role = {t: "MAIN" for t, rec in raw.items()
        if ((rec or {}).get("group") or "") in MAIN_GROUPS}

docs = []
t0 = time.time()
for p in SHARDS:
    for g in pq.read_table(p, columns=["general"]).column("general").to_pylist():
        if g:
            s = set(g.split(", "))
            if person_group(s) == GROUP:
                docs.append(s)
print(f"{len(docs):,} posts ({time.time()-t0:.0f}s)")

freq = Counter()
for s in docs:
    freq.update(s)
vocab = {t: i for i, (t, c) in enumerate(freq.most_common()) if c >= 20}
id_to_tag = {i: t for t, i in vocab.items()}
N = len(docs)
P = {t: freq[t] / N for t in vocab}
indptr = np.zeros(N + 1, dtype=np.int64)
buf = []
for i, s in enumerate(docs):
    buf.extend(sorted(vocab[t] for t in s if t in vocab))
    indptr[i + 1] = len(buf)
indices = np.asarray(buf, dtype=np.int32)
post_of = np.repeat(np.arange(N, dtype=np.int32), np.diff(indptr))
order = np.argsort(indices, kind="stable")
inv_posts = post_of[order]
bounds = np.searchsorted(indices[order], np.arange(len(vocab) + 1))
main_ids = np.zeros(len(vocab), dtype=bool)
for t, i in vocab.items():
    if role.get(t) == "MAIN":
        main_ids[i] = True


def postings(t):
    i = vocab.get(t)
    return None if i is None else inv_posts[bounds[i]:bounds[i + 1]]


def match(tags, floor=40):
    use = sorted(tags, key=lambda t: freq.get(t, 0))
    while True:
        ps = [p for p in (postings(t) for t in use) if p is not None]
        if not ps:
            return None, use
        ps.sort(key=len)
        cur = ps[0]
        for nxt in ps[1:]:
            cur = np.intersect1d(cur, nxt, assume_unique=True)
        if len(cur) >= floor or len(use) <= 1:
            return cur, use
        use.pop(0)


def combos(prompt, dedupe, max_size=4, top=5, min_count=6):
    cur, used = match(prompt)
    if cur is None or not len(cur):
        return [], 0
    m = len(cur)
    cnt = np.zeros(len(vocab), dtype=np.int32)
    for pi in cur:
        cnt[indices[indptr[pi]:indptr[pi + 1]]] += 1
    cand = []
    for c in np.nonzero(cnt)[0]:
        t = id_to_tag[int(c)]
        if t in prompt or not main_ids[c] or cnt[c] < min_count:
            continue
        pb = P[t]
        if pb > 0.30 or (cnt[c] / m) / pb < 2.0:
            continue
        cand.append(int(c))
    keep = np.zeros(len(vocab), dtype=bool)
    keep[cand] = True
    # 후보끼리의 함의쌍을 미리 계산한다(조합 안에 둘 다 들어가면 한 칸 낭비).
    impl = set()
    if dedupe:
        for i, ci in enumerate(cand):
            ti = id_to_tag[ci]
            pi_arr = postings(ti)
            for cj in cand[i + 1:]:
                tj = id_to_tag[cj]
                if same_family(ti, tj):
                    impl.add((ci, cj)); impl.add((cj, ci))
                    continue
                pj_arr = postings(tj)
                inter = len(np.intersect1d(pi_arr, pj_arr, assume_unique=True))
                if not inter:
                    continue
                if (inter / len(pi_arr) >= IMPLICATION_CONF
                        or inter / len(pj_arr) >= IMPLICATION_CONF):
                    impl.add((ci, cj)); impl.add((cj, ci))
    tally = Counter()
    for pi in cur:
        row = indices[indptr[pi]:indptr[pi + 1]]
        sel = [int(x) for x in row if keep[x]]
        if len(sel) < 2:
            continue
        sel.sort(key=lambda c: -((cnt[c] / m) / max(P[id_to_tag[c]], 1e-9)))
        picked = []
        for c in sel:
            if dedupe and any((c, q) in impl for q in picked):
                continue
            picked.append(c)
            if len(picked) >= max_size:
                break
        if len(picked) >= 2:
            tally[tuple(sorted(picked))] += 1
    out = []
    for combo, n in tally.most_common(60):
        if n < min_count:
            break
        names = [id_to_tag[c] for c in combo]
        surp = sum(-math.log2(P[t]) for t in names)
        out.append((n * math.log2(1 + surp), n, surp, names))
    out.sort(reverse=True)
    return out[:top], m


for q in (["sword"], ["office lady"], ["maid"], ["beach", "smile"]):
    print(f"\n=== {', '.join(q)} ===")
    for dedupe in (False, True):
        t0 = time.time()
        res, m = combos(set(q), dedupe)
        ms = (time.time() - t0) * 1000
        avg = sum(s for _, _, s, _ in res) / max(len(res), 1)
        print(f"  [{'중복제거' if dedupe else '원래   '}] {ms:>6.0f}ms  "
              f"평균 정보량 {avg:>5.1f} bit")
        for _, n, s, names in res:
            print(f"      {n:>5}x ({s:>4.1f}b)  " + " + ".join(names))
