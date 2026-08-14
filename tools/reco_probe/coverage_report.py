# -*- coding: utf-8 -*-
"""커버리지 전수 측정 - 인원 그룹별 · 어휘 전체 · NSFW 포함.

지금까지 잰 것은 `1girl_solo` 의 held-out 지표뿐이었다. 그것만으로는
"어떤 태그를 골랐을 때 답이 나오는가" 를 모른다. 여기서는 **어휘 전체**를 훑는다.

  1. 그룹별 단독 태그 커버리지 - 어휘의 몇 %가 조합을 내는가
  2. 빈도 구간별 커버리지 - 희귀 태그가 버려지고 있지 않은가
  3. **NSFW 커버리지** - 성인/금기 어휘가 일반 어휘와 같은 대접을 받는가
     (이 시스템은 사용자가 원하는 조합을 막지 않는 것이 제약이다)
  4. 등급 구성 - e 등급이 두꺼운 그룹에서 성인 태그가 실제로 답을 내는가

시간이 걸린다(그룹당 어휘 수천 개). --sample 로 표본만 볼 수 있다.

    python tools/reco_probe/coverage_report.py --sample 400
    python tools/reco_probe/coverage_report.py --only 1girl_1boy
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.tag_combo.model import ComboModel        # noqa: E402
from core.tag_combo.person import PERSON_GROUPS    # noqa: E402
from core.tag_combo.query import ComboQuery, Policy  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
D = ROOT / "data" / "tag_combo"
NSFW_DIR = ROOT / "wildcards" / "nsfw"
BANDS = [(0, 100), (100, 500), (500, 2_000), (2_000, 10_000),
         (10_000, 1 << 30)]


def adult_vocab() -> set[str]:
    """성인 도감 어휘. **거르는 데 쓰지 않는다** - 커버리지를 따로 세기 위한 것이다."""
    out: set[str] = set()
    p = ROOT / "data" / "interactive_adult_tags.json"
    if p.exists():
        out |= set(json.loads(p.read_text(encoding="utf-8")).get("tags") or ())
    if NSFW_DIR.exists():
        for f in NSFW_DIR.glob("nsfw_*.txt"):
            out |= {l.strip() for l in f.read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.startswith("#")}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="조합 추천 커버리지 전수")
    ap.add_argument("--only", default="")
    ap.add_argument("--sample", type=int, default=0,
                    help="그룹당 이 개수만 표본으로 본다(0=전수)")
    ap.add_argument("--seed", type=int, default=20260814)
    args = ap.parse_args()

    adult = adult_vocab()
    print(f"성인 어휘 {len(adult):,}개 (커버리지 분리 집계용, 필터 아님)\n")
    groups = [args.only] if args.only else list(PERSON_GROUPS)

    print(f"{'group':<30}{'어휘':>8}{'검사':>7}{'조합있음':>9}{'비율':>7}"
          f"{'성인검사':>9}{'성인있음':>9}{'성인비율':>9}{'초':>7}")
    totals = {"v": 0, "n": 0, "ok": 0, "an": 0, "aok": 0}
    per_group = {}
    for grp in groups:
        p = D / f"{grp}.ncsr"
        if not p.exists():
            print(f"{grp:<30}   (모델 없음)")
            continue
        m = ComboModel(p)
        m.ensure_inverted()
        q = ComboQuery(m, Policy())
        tags = list(m.tags)
        if args.sample and len(tags) > args.sample:
            tags = random.Random(args.seed).sample(tags, args.sample)
        t0 = time.time()
        ok = an = aok = 0
        band_n = {b: 0 for b in BANDS}
        band_ok = {b: 0 for b in BANDS}
        for t in tags:
            r = q.recommend([t])
            good = bool(r.combos)
            ok += good
            f = int(m.freq[m.tag_to_id[t]])
            for b in BANDS:
                if b[0] <= f < b[1]:
                    band_n[b] += 1
                    band_ok[b] += good
                    break
            if t in adult:
                an += 1
                aok += good
        el = time.time() - t0
        per_group[grp] = (band_n, band_ok)
        totals["v"] += m.header.vocab; totals["n"] += len(tags)
        totals["ok"] += ok; totals["an"] += an; totals["aok"] += aok
        print(f"{grp:<30}{m.header.vocab:>8,}{len(tags):>7,}{ok:>9,}"
              f"{ok/max(len(tags),1):>7.0%}{an:>9,}{aok:>9,}"
              f"{aok/max(an,1):>9.0%}{el:>7.0f}")
    print(f"{'합계':<30}{totals['v']:>8,}{totals['n']:>7,}{totals['ok']:>9,}"
          f"{totals['ok']/max(totals['n'],1):>7.0%}{totals['an']:>9,}"
          f"{totals['aok']:>9,}{totals['aok']/max(totals['an'],1):>9.0%}")

    print(f"\n빈도 구간별 커버리지 (전 그룹 합계)")
    print(f"{'빈도':<18}{'검사':>9}{'조합있음':>10}{'비율':>8}")
    for b in BANDS:
        n = sum(per_group[g][0][b] for g in per_group)
        k = sum(per_group[g][1][b] for g in per_group)
        lo, hi = b
        label = f"{lo:,}~" + ("" if hi > 1 << 20 else f"{hi:,}")
        print(f"{label:<18}{n:>9,}{k:>10,}{n and k/n or 0:>8.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
