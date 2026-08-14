# -*- coding: utf-8 -*-
"""의상 -> 신체 함의가 lift 게이트에서 얼마나 죽는가 - 문제 규모 측정.

사용자 지적: 사용자는 의상-신체-액션 관계를 어려워한다. state_system 이 상태
분류를 시도한 이유가 그것이다.

내 시스템은 '함께 나타나면 추천' 만 한다. 그런데 의상->신체는 다른 관계다 -
**입으면 그렇게 되는** 함의다. 지금은 둘을 같은 lift 잣대로 재서, 인과적으로
확실하지만 통계적으로 평범한 쌍이 탈락한다(see-through -> nipples, lift 1.82).

여기서 재는 것:
  (a) 의상 태그 -> 신체 태그 중 conf 는 높은데 lift 로 탈락하는 쌍이 몇 개인가
  (b) 반대로 lift 는 높은데 conf 가 낮아 '입으면 그렇게 된다' 고 말할 수 없는 쌍
  (c) 액션(포즈) 방향도 같은 문제인가
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, r"C:\VNR\DEV\NAIA2.0")
from core.tag_combo.model import ComboModel   # noqa: E402

ROOT = Path(r"C:\VNR\DEV\NAIA2.0")
axes = json.loads((ROOT / "data" / "interactive_axis_tags.json")
                  .read_text(encoding="utf-8"))["axes"]
raw = json.loads((ROOT / "data" / "interactive_tags.json")
                 .read_text(encoding="utf-8"))

CLOTH = {t for k in axes if k.startswith("cloth") for t in axes[k]}
BODY = {t for k in axes if k.startswith(("body_", "skin", "marking")) for t in axes[k]}
BODY |= {t for t, r in raw.items() if ((r or {}).get("group") or "") == "Person_Body"}
POSE = {t for k in axes if k.startswith("pose") for t in axes[k]}

m = ComboModel(ROOT / "data" / "tag_combo" / "1girl_solo.ncsr")
m.ensure_inverted()
N = m.header.posts
print(f"1girl_solo {N:,} 게시물 · 의상 {len(CLOTH & set(m.tags)):,} · "
      f"신체 {len(BODY & set(m.tags)):,} · 자세 {len(POSE & set(m.tags)):,}")

MIN_SEED = 300
CONF_HI = 0.30          # '입으면 대체로 그렇게 된다' 의 하한
LIFT_GATE, PB_GATE = 2.0, 0.30


def scan(src: set, dst: set, label: str):
    seeds = [t for t in src if t in m.tag_to_id
             and int(m.freq[m.tag_to_id[t]]) >= MIN_SEED]
    dsts = [t for t in dst if t in m.tag_to_id]
    did = {t: m.tag_to_id[t] for t in dsts}
    pb = {t: float(m.freq[i]) / N for t, i in did.items()}
    kept = dropped_lift = dropped_pb = 0
    examples = []
    t0 = time.time()
    for s in seeds:
        posts = m.postings(s)
        ns = len(posts)
        if not ns:
            continue
        cnt = np.zeros(m.header.vocab, dtype=np.int32)
        ip, ix = m.indptr, m.indices
        for p in posts:
            cnt[ix[ip[p]:ip[p + 1]]] += 1
        for t, i in did.items():
            c = int(cnt[i])
            if not c:
                continue
            conf = c / ns
            if conf < CONF_HI:
                continue                      # '대체로 그렇게 된다' 가 아니다
            lift = conf / pb[t] if pb[t] else 0.0
            if pb[t] > PB_GATE:
                dropped_pb += 1
                if len(examples) < 10:
                    examples.append((s, t, conf, pb[t], lift, "P(B) 상한"))
            elif lift < LIFT_GATE:
                dropped_lift += 1
                if len(examples) < 10:
                    examples.append((s, t, conf, pb[t], lift, "lift 하한"))
            else:
                kept += 1
    el = time.time() - t0
    tot = kept + dropped_lift + dropped_pb
    print(f"\n[{label}] 씨앗 {len(seeds):,} · conf>={CONF_HI} 인 쌍 {tot:,} "
          f"({el:.0f}s)")
    print(f"   통과 {kept:,} ({kept/max(tot,1):.0%}) · "
          f"lift 탈락 {dropped_lift:,} ({dropped_lift/max(tot,1):.0%}) · "
          f"P(B) 탈락 {dropped_pb:,} ({dropped_pb/max(tot,1):.0%})")
    for s, t, c, p, l, why in examples:
        print(f"     {s:<24} -> {t:<22} conf {c:.2f} P {p:.3f} lift {l:.2f}  {why}")


scan(CLOTH, BODY, "의상 -> 신체")
scan(CLOTH, POSE, "의상 -> 자세")
scan(POSE, BODY, "자세 -> 신체")
