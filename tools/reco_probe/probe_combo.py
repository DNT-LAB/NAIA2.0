# -*- coding: utf-8 -*-
"""조합을 '묶음으로' 뽑는다 - 이 제품의 핵심 기대.

지금까지 잰 것은 태그 단위 랭킹이다. 사용자가 원하는 것은
"이 구도에는 이 의상 세트가 흔하다" 같은 **묶음**이다.

방법: 매칭된 게시물마다 프롬프트 밖의 MAIN 역할 태그만 남겨 튜플로 만들고 센다.
그대로 세면 긴 꼬리가 전부 1회짜리가 되므로 **역할별로 잘라** 조합 크기를 제한한다.
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
AUX_GROUPS = {"Person_Body", "Composition_Meta"}


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


print("태그 역할표 적재...", flush=True)
raw = json.loads((ROOT / "data" / "interactive_tags.json").read_text(encoding="utf-8"))
role = {}
for t, rec in raw.items():
    grp = (rec or {}).get("group") or ""
    if grp in MAIN_GROUPS:
        role[t] = "MAIN"
    elif grp in AUX_GROUPS:
        role[t] = "AUX"
print(f"  MAIN {sum(1 for v in role.values() if v=='MAIN'):,} / "
      f"AUX {sum(1 for v in role.values() if v=='AUX'):,} / 미분류는 제외")

print("코퍼스 적재...", flush=True)
t0 = time.time()
docs = []
for p in SHARDS:
    for g in pq.read_table(p, columns=["general"]).column("general").to_pylist():
        if g:
            s = set(g.split(", "))
            if person_group(s) == GROUP:
                docs.append(s)
print(f"  {len(docs):,} posts ({time.time()-t0:.0f}s)")

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
print(f"  vocab {len(vocab):,} / nnz {len(indices):,}")

# MAIN 태그 id 집합 + 역할 미분류 처리
main_ids = np.zeros(len(vocab), dtype=bool)
for t, i in vocab.items():
    if role.get(t) == "MAIN":
        main_ids[i] = True
print(f"  어휘 중 MAIN {int(main_ids.sum()):,} / {len(vocab):,}")


def postings(t):
    i = vocab.get(t)
    return None if i is None else inv_posts[bounds[i]:bounds[i + 1]]


def match(tags, floor=40):
    use = sorted(tags, key=lambda t: freq.get(t, 0))
    cur = None
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


def combos(prompt, max_size=4, top=6, min_count=6):
    cur, used = match(prompt)
    if cur is None or not len(cur):
        return [], 0, used
    m = len(cur)
    # 게시물별 MAIN 태그 중 프롬프트 밖 + lift 가 높은 것만 남긴다
    cnt = np.zeros(len(vocab), dtype=np.int32)
    for pi in cur:
        cnt[indices[indptr[pi]:indptr[pi + 1]]] += 1
    keep = np.zeros(len(vocab), dtype=bool)
    for c in np.nonzero(cnt)[0]:
        t = id_to_tag[int(c)]
        if t in prompt or not main_ids[c] or cnt[c] < min_count:
            continue
        pb = P[t]
        if pb > 0.30:
            continue
        if (cnt[c] / m) / pb < 2.0:
            continue
        keep[c] = True
    # 조합 집계 - 게시물마다 상위 max_size 개(빈도 낮은 = 특징적인 것 우선)만
    tally = Counter()
    for pi in cur:
        row = indices[indptr[pi]:indptr[pi + 1]]
        sel = [int(x) for x in row if keep[x]]
        if len(sel) < 2:
            continue
        sel.sort(key=lambda c: -((cnt[c] / m) / max(P[id_to_tag[c]], 1e-9)))
        tally[tuple(sorted(sel[:max_size]))] += 1
    out = []
    for combo, n in tally.most_common(80):
        if n < min_count:
            break
        names = [id_to_tag[c] for c in combo]
        surp = sum(-math.log2(P[t]) for t in names)
        out.append((n * math.log2(1 + surp), n, names))
    out.sort(reverse=True)
    return out[:top], m, used


QUERIES = [
    ["office lady"],
    ["school uniform", "classroom"],
    ["sword"],
    ["maid"],
    ["beach", "smile"],
    ["kimono", "festival"],
]
print(f"\n{'query':<34}{'match':>8}{'ms':>7}  조합")
for q in QUERIES:
    t0 = time.time()
    res, m, used = combos(set(q))
    ms = (time.time() - t0) * 1000
    drop = "" if set(used) == set(q) else f" (백오프->{','.join(used)})"
    print(f"{', '.join(q):<34}{m:>8,}{ms:>7.0f}{drop}")
    for _, n, names in res:
        print(f"      {n:>5}x  " + " + ".join(names))
