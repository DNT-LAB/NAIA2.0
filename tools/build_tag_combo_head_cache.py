# -*- coding: utf-8 -*-
"""넓은 단독 질의를 위한 헤드 컨텍스트 캐시를 굽는다.

## 왜

매칭 집합이 크면 질의 시점 계산이 초 단위가 된다(실측):

    office lady        1,862 매칭    20ms
    maid              15,328        153ms
    looking at viewer 494,399      5,608ms   <- 못 쓴다

경계는 5,000건 근처다. 그런데 그런 태그는 많지 않다 - 그래서 **전량 계산 결과를
그대로 담는다.** 표본추출로 때우면 답이 망가진다(실측: 4만 건으로 자르면
`hetero -> sex + vaginal + missionary` 가 `fisting + anal fisting` 이 된다).

## 쓰는 법

    python tools/build_tag_combo_head_cache.py --min-matched 5000
    python tools/build_tag_combo_head_cache.py --only 1girl_solo --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tag_combo.model import ComboModel                    # noqa: E402
from core.tag_combo.person import PERSON_GROUPS                # noqa: E402
from core.tag_combo.query import ComboQuery, Policy            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "tag_combo"


def main() -> int:
    ap = argparse.ArgumentParser(description="헤드 컨텍스트 캐시 생성")
    ap.add_argument("--min-matched", type=int, default=5000,
                    help="매칭이 이보다 크면 캐시한다. 실측 경계가 5,000 근처다")
    ap.add_argument("--top", type=int, default=20, help="컨텍스트당 담을 튜플 수")
    ap.add_argument("--only", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    groups = [args.only] if args.only else list(PERSON_GROUPS)
    print(f"{'group':<30}{'대상':>7}{'캐시':>7}{'초':>8}{'KB':>8}")
    for grp in groups:
        p = D / f"{grp}.ncsr"
        if not p.exists():
            print(f"{grp:<30}   (모델 없음 - build_tag_combo_models.py 먼저)")
            continue
        m = ComboModel(p)
        m.ensure_inverted()
        # 캐시를 만들 때는 **캐시를 보지 않는다**(재귀 방지). head 를 비운 사본으로 판다.
        m._head = {}
        q = ComboQuery(m, Policy(top_k=args.top))
        want = [t for t in m.tags
                if int(m.freq[m.tag_to_id[t]]) >= args.min_matched]
        head: dict[str, dict] = {}
        t0 = time.time()
        for i, t in enumerate(want, 1):
            r = q.recommend([t])
            if not r.combos:
                continue
            head[t] = {"matched": r.matched,
                       "combos": [[c.tags, c.support] for c in r.combos]}
            if i % 100 == 0:
                print(f"    {i}/{len(want)}  {time.time()-t0:.0f}s", flush=True)
        el = time.time() - t0
        blob = json.dumps(head, ensure_ascii=False)
        print(f"{grp:<30}{len(want):>7}{len(head):>7}{el:>8.0f}{len(blob)/1024:>8.0f}")
        if args.dry_run:
            continue
        meta_path = p.with_suffix(".json")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["head"] = head
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if args.dry_run:
        print("\n--dry-run: 쓰지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
