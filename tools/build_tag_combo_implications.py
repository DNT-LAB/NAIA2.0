# -*- coding: utf-8 -*-
"""조합 안의 함의 중복을 없애기 위한 인접표를 굽는다.

## 왜

`sword` 가 `holding + weapon + holding weapon + holding sword` 를 냈다. 넷이 서로
함의라 네 칸을 한 칸으로 쓴 셈이다. 질의 시점에 후보쌍을 다 계산하면 실측
10~20배(19ms -> 1,440ms)가 되므로, 함의는 **빌드 시점에** 굽는다.

판정은 `build_tag_cooccurrence.py` 와 같다 - 조건부 확률의 비대칭이다:

    P(B|A) >= 0.95  또는  P(A|B) >= 0.95   =>  둘은 부모/자식이다

동족(머리 명사 동일)은 문자열 규칙이라 런타임에서 공짜로 처리한다. 여기서
굽는 것은 통계로만 알 수 있는 함의다.

## 어휘를 좁힌다

전 어휘 쌍은 어림도 없다(13,201^2 = 1.7억). 조합 후보가 될 수 있는 태그만 본다 -
전역 확률 <= 0.30(배경 상한) 이면서 최소 등장 수를 넘는 것. 실측으로 1girl_solo
에서 약 1만 개이고, 포스팅 교집합을 도는 데 몇 분이면 끝난다.

## 쓰는 법

    python tools/build_tag_combo_implications.py --only 1girl_solo
    python tools/build_tag_combo_implications.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tag_combo.model import ComboModel        # noqa: E402
from core.tag_combo.person import PERSON_GROUPS    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "tag_combo"
CONF = 0.95


def main() -> int:
    ap = argparse.ArgumentParser(description="함의 인접표 생성")
    ap.add_argument("--conf", type=float, default=CONF,
                    help="이 이상이면 부모/자식으로 본다 (기본 0.95)")
    ap.add_argument("--min-freq", type=int, default=60,
                    help="이보다 드문 태그는 함의를 못 믿는다")
    ap.add_argument("--max-prob", type=float, default=0.30,
                    help="배경 상한. 이보다 흔하면 어차피 후보가 아니다")
    ap.add_argument("--only", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    groups = [args.only] if args.only else list(PERSON_GROUPS)
    print(f"{'group':<30}{'어휘':>8}{'대상':>8}{'함의쌍':>9}{'초':>7}{'KB':>8}")
    for grp in groups:
        p = D / f"{grp}.ncsr"
        if not p.exists():
            print(f"{grp:<30}   (모델 없음)")
            continue
        m = ComboModel(p)
        m.ensure_inverted()
        n = max(1, m.header.posts)
        prob = m.freq / n
        want = [i for i in range(m.header.vocab)
                if m.freq[i] >= args.min_freq and prob[i] <= args.max_prob]
        # 포스팅을 미리 뽑아 둔다. 길이 순으로 보면 큰 쪽을 일찍 버릴 수 있다.
        posts = {i: m.postings(m.tags[i]) for i in want}
        order = sorted(want, key=lambda i: int(m.freq[i]))
        pairs: dict[str, list[str]] = {}
        cnt = 0
        t0 = time.time()
        for a_pos, a in enumerate(order):
            pa = posts[a]
            na = len(pa)
            if not na:
                continue
            # P(B|A) >= conf 이려면 |A ∩ B| >= conf*|A| 이고, 그러려면
            # |B| >= conf*|A| 여야 한다. 더 드문 것부터 보므로 뒤쪽만 본다.
            need = args.conf * na
            for b in order[a_pos + 1:]:
                pb = posts[b]
                if len(pb) < need:
                    continue
                inter = len(np.intersect1d(pa, pb, assume_unique=True))
                if not inter:
                    continue
                if inter / na >= args.conf or inter / len(pb) >= args.conf:
                    ta, tb = m.tags[a], m.tags[b]
                    pairs.setdefault(ta, []).append(tb)
                    pairs.setdefault(tb, []).append(ta)
                    cnt += 1
            if a_pos and a_pos % 2000 == 0:
                print(f"    {a_pos}/{len(order)}  {time.time()-t0:.0f}s "
                      f"쌍 {cnt:,}", flush=True)
        el = time.time() - t0
        blob = json.dumps(pairs, ensure_ascii=False)
        print(f"{grp:<30}{m.header.vocab:>8,}{len(order):>8,}{cnt:>9,}"
              f"{el:>7.0f}{len(blob)/1024:>8.0f}")
        if args.dry_run:
            continue
        meta_path = p.with_suffix(".json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["implies"] = pairs
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if args.dry_run:
        print("\n--dry-run: 쓰지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
