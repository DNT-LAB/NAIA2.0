# -*- coding: utf-8 -*-
"""인원 그룹별 모델이 실제로 얼마나 커지나 - 전수 측정(150샤드).

CSR 을 만들지 않고 카운터만 돌려 어휘/nnz 를 정확히 센다. 그 값으로 포맷별
메모리를 계산한다. 사용자가 지목한 제약이 '메모리에 올라가고 검색하는 모델의
성능 한계' 이므로 이 숫자가 설계를 가른다.
"""
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(r"C:\VNR\DEV\NAIA2.0")
SHARDS = sorted((ROOT / "data" / "tags").glob("tags_*.parquet"),
                key=lambda p: int(p.stem.split("_")[1]))
MIN_FREQ = 20


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


t0 = time.time()
posts = Counter()
nnz_raw = Counter()
freq = defaultdict(Counter)
rating_mix = defaultdict(Counter)
for n, p in enumerate(SHARDS, 1):
    tb = pq.read_table(p, columns=["general", "rating"])
    gs = tb.column("general").to_pylist()
    rs = tb.column("rating").to_pylist()
    for g, r in zip(gs, rs):
        if not g:
            continue
        s = set(g.split(", "))
        grp = person_group(s)
        posts[grp] += 1
        nnz_raw[grp] += len(s)
        freq[grp].update(s)
        rating_mix[grp][r or "?"] += 1
    if n % 30 == 0:
        print(f"  {n}/{len(SHARDS)} shards  {time.time()-t0:.0f}s", flush=True)
print(f"scan {time.time()-t0:.0f}s  total posts {sum(posts.values()):,}")

rows = []
for grp in sorted(posts, key=lambda k: -posts[k]):
    f = freq[grp]
    vocab = [t for t, c in f.items() if c >= MIN_FREQ]
    kept = sum(c for t, c in f.items() if c >= MIN_FREQ)
    rows.append((grp, posts[grp], len(f), len(vocab), nnz_raw[grp], kept,
                 dict(rating_mix[grp].most_common())))

print(f"\n{'group':<30}{'posts':>10}{'uniq tag':>10}{'vocab>=20':>11}"
      f"{'nnz(all)':>12}{'nnz(vocab)':>12}{'tags/post':>10}")
for grp, np_, uq, vc, nz, kp, _ in rows:
    print(f"{grp:<30}{np_:>10,}{uq:>10,}{vc:>11,}{nz:>12,}{kp:>12,}{kp/max(np_,1):>10.1f}")

print(f"\n{'group':<30}{'CSR uint16':>12}{'inv int32':>11}{'indptr':>9}{'합계':>10}")
tot = 0
for grp, np_, uq, vc, nz, kp, _ in rows:
    csr = kp * 2 / 1e6
    inv = kp * 4 / 1e6
    ip = (np_ + 1) * 4 / 1e6
    s = csr + inv + ip
    tot += s
    print(f"{grp:<30}{csr:>11.0f}M{inv:>10.0f}M{ip:>8.0f}M{s:>9.0f}M")
print(f"{'전부 상주하면':<30}{'':>12}{'':>11}{'':>9}{tot:>9.0f}M")

print("\n등급 구성:")
for grp, np_, uq, vc, nz, kp, rm in rows[:6]:
    print(f"  {grp:<30}{rm}")

out = ROOT.parent / "codex_ws" / "person_group_stats.json"
try:
    out.write_text(json.dumps(
        {"minFreq": MIN_FREQ,
         "groups": [{"group": g, "posts": p, "uniqueTags": u, "vocab": v,
                     "nnzAll": n, "nnzVocab": k, "ratings": rm}
                    for g, p, u, v, n, k, rm in rows]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {out}")
except OSError as exc:
    print(f"\n(저장 실패: {exc})")
