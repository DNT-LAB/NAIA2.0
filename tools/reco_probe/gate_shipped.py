# -*- coding: utf-8 -*-
"""반증 실험 8.1 / 8.2 를 **배포되는 코드 경로**로 다시 돌린다.

## 왜 다시 도는가

처음엔 독립 프로브(`probe_bundle_hit2.py` 등)로 쟀다. 그런데 프로덕션
`core/tag_combo/query.py` 에는 프로브에 없는 것이 더 붙어 있다 - 게이트 백오프,
캐릭터 집중도 필터, 크기 백오프, 동족 중복 제거, 점수 정렬 순서.

Codex 게이트가 이걸 측정했다: **120건 중 24건만 일치.** 즉 프로브로 얻은
숫자가 배포된 코드를 설명하지 않는다. 그래서 같은 지표를 **ComboQuery 그대로**
돌려 다시 잰다.

지표는 SPEC 8.1 과 같다:
    ExactBundleHit_i@K = 1[ 어떤 반환 튜플 B 가 통째로 숨긴 태그 안에 있고,
                            그 튜플이 **정보성 태그**(전역 P <= 0.05)로만 이뤄졌다 ]
자명한 베이스라인이 0점을 받아야 한다 - `1girl`/`solo` 는 그룹 안에서 확률이
1.0 이라 그것으로 만든 조합은 언제나 "맞는다".

## 쓰는 법

    python tools/reco_probe/gate_shipped.py
    python tools/reco_probe/gate_shipped.py --group 2girls --trials 400
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.tag_combo.model import ComboModel      # noqa: E402
from core.tag_combo.person import person_group_of  # noqa: E402
from core.tag_combo.query import ComboQuery, Policy  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
HOLD_SHARDS = (118, 120, 122)
INFO_MAX_P = 0.05


def load_holdout(group: str) -> list[tuple[set, set]]:
    out = []
    for i in HOLD_SHARDS:
        p = ROOT / "data" / "tags" / f"tags_{i}.parquet"
        tb = pq.read_table(p, columns=["general", "character"])
        gs = tb.column("general").to_pylist()
        cs = tb.column("character").to_pylist()
        for g, c in zip(gs, cs):
            if not g:
                continue
            s = set(g.split(", "))
            if person_group_of(s) == group:
                out.append((s, {x for x in (c or "").split(", ") if x}))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="1girl_solo")
    ap.add_argument("--trials", type=int, default=800)
    ap.add_argument("--prompt", type=int, default=3)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20260814)
    args = ap.parse_args()

    mp = ROOT / "data" / "tag_combo" / f"{args.group}.ncsr"
    if not mp.exists():
        print(f"!! 모델이 없다: {mp} - tools/build_tag_combo_models.py 먼저")
        return 2
    t0 = time.time()
    model = ComboModel(mp)
    model.ensure_inverted()
    print(f"모델 {args.group}: {model.header.posts:,} 게시물 / "
          f"어휘 {model.header.vocab:,} / {time.time()-t0:.1f}s")

    n = max(1, model.header.posts)
    prob = model.freq / n
    info = {model.tags[i] for i in range(model.header.vocab)
            if prob[i] <= INFO_MAX_P}

    hold = load_holdout(args.group)
    rng = random.Random(args.seed)
    cases = [(s, c) for s, c in hold if len(s) >= args.prompt + 6]
    rng.shuffle(cases)
    cases = cases[:args.trials]
    prepared = []
    for s, _ in cases:
        tg = sorted(s); rng.shuffle(tg)
        prepared.append((set(tg[:args.prompt]), set(tg[args.prompt:])))
    print(f"홀드아웃 {len(hold):,} -> 평가 {len(prepared)}건 "
          f"(샤드 {HOLD_SHARDS}, 학습과 다른 시기)")

    q = ComboQuery(model, Policy(top_k=args.top))

    # 베이스라인 A - 무조건 헤드 튜플(코퍼스 최빈 태그 조합)
    head = [model.tags[i] for i in np.argsort(-model.freq)[:40]]
    head_tuples = [list(c) for c in combinations(head[:8], 3)][:40]

    def rec_head(prompt):
        out = []
        for t in head_tuples:
            if set(t) & prompt:
                continue
            out.append(t)
            if len(out) >= args.top:
                break
        return out

    def rec_model(prompt):
        return [c.tags for c in q.recommend(sorted(prompt)).combos]

    print(f"\n{'method':<26}{'Hit@K':>8}{'Hit_i@K':>10}{'정보튜플율':>11}"
          f"{'빈답':>7}{'ms':>8}")
    res = {}
    for name, fn in (("A. 무조건 헤드 튜플", rec_head),
                     ("D. 배포 코드 (ComboQuery)", rec_model)):
        hit = hi = empty = 0
        it = tt = 0
        per = []
        t0 = time.time()
        for prompt, held in prepared:
            r = fn(prompt)
            if not r:
                empty += 1
            ok = [b for b in r if set(b) <= held and not (set(b) & prompt)]
            oki = [b for b in ok if set(b) <= info]
            hit += 1 if ok else 0
            per.append(1 if oki else 0)
            hi += per[-1]
            it += sum(1 for b in r if set(b) <= info); tt += len(r)
        ms = (time.time() - t0) * 1000 / len(prepared)
        res[name] = per
        print(f"{name:<26}{hit/len(prepared):>8.3f}{hi/len(prepared):>10.3f}"
              f"{it/max(tt,1):>11.3f}{empty:>7}{ms:>8.1f}")

    d = [x - y for x, y in zip(res["D. 배포 코드 (ComboQuery)"],
                               res["A. 무조건 헤드 튜플"])]
    rb = random.Random(7)
    boots = sorted(sum(rb.choice(d) for _ in range(len(d))) / len(d)
                   for _ in range(2000))
    lo, hi_ci = boots[50], boots[1949]
    print(f"\n배포 코드 - 무조건 헤드: {sum(d)/len(d):+.4f} "
          f"95% CI [{lo:+.4f}, {hi_ci:+.4f}]")
    print("판정:", "유의하게 이긴다" if lo > 0 else
          ("유의하지 않다" if hi_ci > 0 else "진다 - 설계를 재검토하라"))
    return 0 if lo > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
