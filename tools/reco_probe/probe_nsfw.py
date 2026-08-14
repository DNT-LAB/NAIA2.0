# -*- coding: utf-8 -*-
"""NSFW 품질 점검 - 눈으로 봐야 아는 것.

이 시스템의 제약은 '사용자가 원하는 조합을 막지 않는다' 다. 그래서 확인할 것은
'성인 태그가 나오는가' 가 아니라 **성인 컨텍스트에서 답이 쓸 만한가** 다.
빈 답이거나 배경 태그만 나오면 막은 것과 실질적으로 같다.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\VNR\DEV\NAIA2.0")
from core.tag_combo.model import ComboModel          # noqa: E402
from core.tag_combo.query import ComboQuery, Policy  # noqa: E402

D = Path(r"C:\VNR\DEV\NAIA2.0\data\tag_combo")

CASES = {
    # e 등급이 50% 인 그룹 - 성인 조합의 본진이다
    "1girl_1boy": [
        ["hetero"], ["sex"], ["vaginal"], ["fellatio"], ["paizuri"],
        ["cum on body"], ["nipples", "sweat"], ["bondage"], ["rape"],
        ["clothed sex"], ["cowgirl position"], ["anal"],
    ],
    "1girl_solo": [
        ["masturbation"], ["nude"], ["pussy"], ["bdsm"], ["tentacles"],
        ["loli"], ["breast grab"], ["spread legs"], ["ahegao"],
        ["urethral insertion"], ["guro"], ["bestiality"],
    ],
    "multiple_girls_multiple_boys": [
        ["group sex"], ["gangbang"], ["orgy"],
    ],
    "2girls": [
        ["yuri"], ["tribadism"], ["kiss"],
    ],
}


def show(grp, cases):
    p = D / f"{grp}.ncsr"
    if not p.exists():
        print(f"=== {grp} : 모델 없음")
        return
    m = ComboModel(p)
    m.ensure_inverted()
    q = ComboQuery(m, Policy())
    print(f"\n=== {grp}  (게시물 {m.header.posts:,} / 등급 g{m.header.ratings[0]:,} "
          f"s{m.header.ratings[1]:,} q{m.header.ratings[2]:,} e{m.header.ratings[3]:,})")
    for pr in cases:
        known = [t for t in pr if t in m.tag_to_id]
        if not known:
            print(f"  [{', '.join(pr)}]  어휘에 없음")
            continue
        t0 = time.time()
        r = q.recommend(pr)
        ms = (time.time() - t0) * 1000
        n = m.freq[m.tag_to_id[known[0]]]
        flag = " [약함]" if r.weak else ""
        print(f"  [{', '.join(pr):<24}] freq {int(n):>7,} · 매칭 {r.matched:>7,} "
              f"· {ms:>6.0f}ms{flag}")
        if not r.combos:
            print("        (없음)")
        for c in r.combos[:3]:
            print(f"        {c.support:>5}x ({c.surprisal:>4.0f}b)  " + " + ".join(c.tags))


for grp, cases in CASES.items():
    show(grp, cases)
