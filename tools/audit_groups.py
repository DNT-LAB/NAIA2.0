# -*- coding: utf-8 -*-
"""인원 그룹 전수 감사 — `1girl_solo` 말고 나머지 12그룹은 어떤가.

## 왜

지금까지 축 감사를 전부 `1girl_solo` 로 했다. 그런데 축에는 다인원 전용
(`pose_multi`, `*_m`)이 있어서, 1인 모델로 재면 당연히 0% 가 나온다.
실제로 `pose_multi` 2.3% 가 그렇게 나왔는데 그게 결함인지 측정 오류인지
그룹을 맞춰 재기 전에는 알 수 없다.

## 재는 것

    그룹별   앵커 수 · 답변율 · 커버리지 중앙 · 잔여오염
    축 x 그룹  다인원 축을 다인원 그룹에서 재면 살아나나
    무작위 표본  실제 출력이 읽을 만한가 (숫자로는 안 보이는 것)

## 쓰는 법

    python tools/audit_groups.py
    python tools/audit_groups.py --sample 12 --seed 7
"""
from __future__ import annotations

import argparse
import json
import random
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.tag_combo.noise import is_color_tag, is_framing_tag   # noqa: E402
from core.tag_combo.person import PERSON_GROUPS                 # noqa: E402

# 다인원 축은 이름으로 알 수 있다. 이걸 1인 그룹에서 재면 0% 가 정상이다.
def is_multi_axis(a: str) -> bool:
    return a.endswith("_m") or "_m_" in a or a in ("pose_multi", "pose_multi_relation")


# 그룹이 몇 인분인가 - 다인원 축을 어디서 재야 하는지 정한다.
MULTI_GROUPS = ("1girl_1boy", "2girls", "2boys", "multiple_girls", "multiple_boys",
                "1girl_multiple_boys", "1boy_multiple_girls",
                "multiple_girls_multiple_boys")


def main() -> int:
    ap = argparse.ArgumentParser(description="인원 그룹별 조합 추천 감사")
    ap.add_argument("--sample", type=int, default=10, help="그룹당 무작위 표본 수")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--min-cov", type=float, default=0.02)
    args = ap.parse_args()

    ax = json.loads((ROOT / "data/interactive_axis_tags.json")
                    .read_text(encoding="utf-8"))["axes"]
    bank = json.loads((ROOT / "data/tag_combo/recipe_bank.json")
                      .read_text(encoding="utf-8"))["groups"]
    rng = random.Random(args.seed)

    print(f"{'그룹':<30} {'앵커':>8} {'커버중앙':>9} {'2%미만':>8} {'잔여오염':>9}")
    print("-" * 70)
    for g in PERSON_GROUPS:
        tab = bank.get(g) or {}
        rows = [r[0] for r in tab.values() if r]
        if not rows:
            print(f"{g:<30} {'(비어 있음)':>8}")
            continue
        covs = [r["coverage"] for r in rows]
        weak = sum(1 for c in covs if c < args.min_cov)
        chips = [t for r in rows for t in r["tags"]]
        dirty = sum(1 for c in chips if is_color_tag(c) or is_framing_tag(c))
        print(f"{g:<30} {len(tab):>8,} {st.median(covs):>9.1%} "
              f"{weak/len(covs):>8.1%} {dirty/max(1,len(chips)):>9.2%}")

    # ---- 다인원 축을 맞는 그룹에서 재면 살아나나 --------------------
    print("\n" + "=" * 70)
    print("다인원 축 — 1인 그룹 vs 다인원 그룹")
    print("=" * 70)
    multi_axes = [a for a in ax if is_multi_axis(a) and len(ax[a]) >= 5]
    print(f"{'축':<24} {'태그':>5} {'1girl_solo':>11} " +
          " ".join(f"{g[:11]:>11}" for g in ("1girl_1boy", "2girls", "multiple_girls")))
    for a in sorted(multi_axes):
        ts = {t.strip().lower() for t in ax[a]}
        cells = []
        for g in ("1girl_solo", "1girl_1boy", "2girls", "multiple_girls"):
            tab = bank.get(g) or {}
            n = sum(1 for t in ts if t in tab and tab[t])
            cells.append(f"{n/len(ts):>10.1%}")
        print(f"{a:<24} {len(ts):>5} " + " ".join(cells))

    # ---- 무작위 표본 출력 ------------------------------------------
    print("\n" + "=" * 70)
    print(f"그룹별 무작위 앵커 {args.sample}개 — 읽어 보고 판단할 것")
    print("=" * 70)
    for g in PERSON_GROUPS:
        tab = bank.get(g) or {}
        keys = [k for k, v in tab.items() if v]
        if not keys:
            continue
        print(f"\n--- {g} (앵커 {len(keys):,}) ---")
        for t in rng.sample(keys, min(args.sample, len(keys))):
            r = tab[t][0]
            print(f"   {r['coverage']:>6.1%}  {t:<26} -> {', '.join(r['tags'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
