# -*- coding: utf-8 -*-
"""앵커별 주변분포에서 **캐릭터 편향** 항목을 걷어낸다.

## 왜

Event Preset 의 동시출현 표에는 캐릭터 정보가 없다. 그래서 특정 캐릭터의
디자인이 통계로 위장해 살아남는다(Codex 게이트 실측):

    cooking      -> horned helmet    한 캐릭터 점유율 100%
    hydrokinesis -> fake horns       100%
    shogi        -> low twintails     94.7%

    PMI 0.3 통과 후보 중 점유율 >50% 가 3.00%, >25% 가 9.15%

이걸 두면 "요리하면 뿔투구를 쓴다" 는 추천이 나간다. 조합이 아니라 **한 캐릭터를
외운 것**이다. NCSR 질의 엔진에는 이미 이 필터가 있는데(`query.py:_char_share`)
증류기에는 없었다.

## 어떻게

NCSR 모델은 게시물마다 `post_char` 를 들고 있다. 앵커의 게시물 집합에서 후보가
같이 나온 게시물들을 모아, **한 캐릭터가 차지하는 최대 비율**을 센다.

무캐릭터(`post_char == 0`) 게시물은 분모에서 뺀다 - 오리지널 그림이 많은 태그를
"편향 없음" 으로 오판하지 않기 위해서다. 대신 캐릭터가 붙은 표본이 너무 적으면
(`--min-char-sample`) 판정을 보류하고 살린다.

## 쓰는 법

    python tools/filter_marginals_char_bias.py --dry-run
    python tools/filter_marginals_char_bias.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.tag_combo.model import ComboModel        # noqa: E402
from core.tag_combo.person import PERSON_GROUPS    # noqa: E402

KINDS = ("clothing", "characteristic", "expression")


def char_shares(m: ComboModel, anchor: str, cands: set[str], *,
                min_sample: int) -> dict[str, tuple[float, int, str]]:
    """후보별 (최대 캐릭터 점유율, 캐릭터가 붙은 표본수, 그 캐릭터 id)."""
    ai = m.tag_to_id.get(anchor)
    if ai is None:
        return {}
    posts = m._inv_posts[m._bounds[ai]:m._bounds[ai + 1]]
    ids = {m.tag_to_id[c]: c for c in cands if c in m.tag_to_id}
    if not ids:
        return {}
    per: dict[int, Counter] = {i: Counter() for i in ids}
    chars, ip, ix = m.post_char, m.indptr, m.indices
    for pi in posts:
        ch = int(chars[pi])
        if not ch:                      # 무캐릭터는 분모에서 뺀다
            continue
        for t in ix[ip[pi]:ip[pi + 1]]:
            c = per.get(int(t))
            if c is not None:
                c[ch] += 1
    out = {}
    for i, name in ids.items():
        c = per[i]
        n = sum(c.values())
        if n < min_sample:              # 표본이 적으면 판정 보류
            out[name] = (0.0, n, "")
            continue
        top, cnt = c.most_common(1)[0]
        out[name] = (cnt / n, n, str(top))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="주변분포에서 캐릭터 편향 제거")
    ap.add_argument("--marginals",
                    default=str(ROOT / "data/tag_combo/anchor_feature_marginals.json"))
    ap.add_argument("--models", default=str(ROOT / "data/tag_combo"))
    ap.add_argument("--max-share", type=float, default=0.50,
                    help="한 캐릭터 점유율 상한. query.py 의 max_char_share 와 맞춘다")
    ap.add_argument("--min-char-sample", type=int, default=8,
                    help="캐릭터가 붙은 표본이 이보다 적으면 판정을 보류하고 살린다")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = Path(args.marginals)
    d = json.loads(src.read_text(encoding="utf-8"))
    t0 = time.time()
    tot = dropped = 0
    worst: list[tuple[float, str, str, str]] = []

    for g in PERSON_GROUPS:
        rec = d["groups"].get(g) or {}
        p = Path(args.models) / f"{g}.ncsr"
        if not p.exists():
            print(f"   {g:<30} 모델 없음 - 건너뜀")
            continue
        m = ComboModel(p)
        m.ensure_inverted()
        gd = gt = 0
        for anchor, kinds in rec.items():
            cands = {t for k in KINDS for t, *_ in (kinds.get(k) or [])}
            if not cands:
                continue
            sh = char_shares(m, anchor, cands, min_sample=args.min_char_sample)
            for k in KINDS:
                items = kinds.get(k)
                if not items:
                    continue
                keep = []
                for it in items:
                    gt += 1
                    s, n, ch = sh.get(it[0], (0.0, 0, ""))
                    if s > args.max_share:
                        gd += 1
                        worst.append((s, g, anchor, it[0]))
                    else:
                        keep.append(it)
                if keep:
                    kinds[k] = keep
                else:
                    kinds.pop(k, None)
        # 후보가 통째로 사라진 앵커는 뺀다
        for a in [a for a, v in rec.items() if not v]:
            rec.pop(a)
        tot += gt
        dropped += gd
        print(f"   {g:<30} {gt:>8,}행 중 {gd:>6,} 버림 ({gd/max(1,gt):>5.2%})")
        del m

    print(f"\n합계 {tot:,}행 중 {dropped:,} 버림 ({dropped/max(1,tot):.2%}) · {time.time()-t0:.0f}s")
    worst.sort(reverse=True)
    print("\n점유율 상위 15 (버려진 것):")
    for s, g, a, t in worst[:15]:
        print(f"   {s:>6.1%}  [{g}] {a} -> {t}")

    if args.dry_run:
        print("\n--dry-run 이라 쓰지 않았다.")
        return 0
    d["charFilter"] = {"maxShare": args.max_share,
                       "minCharSample": args.min_char_sample,
                       "droppedRows": dropped, "totalRows": tot}
    src.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"저장: {src}  ({src.stat().st_size/1e6:.1f}MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
