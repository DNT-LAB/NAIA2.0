# -*- coding: utf-8 -*-
"""자기반복 진단 — 라운드 1 검증.

## 확정된 원인

의미 그래프가 후보 쌍을 `interactive_tags.json` 의 relations 로 연결된 것만
뽑아서(288,580쌍), 관계 항목이 없는 쌍은 **평가조차 안 됐다**:

    panties | underwear   c=1.000   간선 없음
    dildo   | sex toy     c=1.000   간선 없음
    greyscale|monochrome  c=1.000   간선 없음

그래서 1위 행의 18.2% 가 앵커와 conf>=0.95 인 후보를 달고 있었고, 15.2% 는
행 안에 그런 쌍이 있었다. **문턱이 아니라 후보 범위 문제였다.**

동시출현 상위 40 이웃을 후보에 넣어 478,910쌍으로 넓혔고 간선이
4,591 -> 6,244 로 늘었다. 이 스크립트는 그 효과를 검증한다.

**셸이 죽어 preview 런처로 실행한다**(`.claude/launch.json` 의 `diag`).
출력은 `data/tag_combo/_diag_selfrep.txt` 로 남는다.
"""
from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.tag_combo.model import ComboModel        # noqa: E402

ENTAIL, MIN_SUP = 0.95, 30
_OUT = ROOT / "data" / "tag_combo" / "_diag_selfrep.txt"
_BUF: list[str] = []


def print(*a, **k):        # noqa: A001
    _BUF.append(" ".join(str(x) for x in a))


import atexit  # noqa: E402
atexit.register(lambda: _OUT.write_text("\n".join(_BUF), encoding="utf-8"))

PAIRS = [("panties", "underwear"), ("bra", "underwear"), ("dildo", "sex toy"),
         ("vibrator", "sex toy"), ("testicles", "penis"),
         ("bandaged arm", "bandages"), ("greyscale", "monochrome"),
         ("street", "road"), ("hairclip", "hair ornament"),
         ("animal ears", "animal ear fluff"),
         # 살아야 할 것
         ("classroom", "indoors"), ("bedroom", "indoors"), ("beach", "outdoors"),
         ("maid", "apron"), ("dress", "apron"), ("cleavage", "large breasts")]


def main() -> int:
    m = ComboModel(ROOT / "data/tag_combo/1girl_solo.ncsr")
    m.ensure_inverted()
    graph = json.loads((ROOT / "data/tag_combo/semantic_graph.json")
                       .read_text(encoding="utf-8"))
    edges = {frozenset((e["a"], e["b"])): e["why"] for e in graph["edges"]}
    print(f"그래프 간선 {len(edges):,}")

    print("\n=== 문제 쌍이 이제 잡히나 ===")
    for a, b in PAIRS:
        e = edges.get(frozenset((a, b)))
        print(f"   {a+' | '+b:<36} {e or '(간선 없음)'}")

    # 뱅크는 아직 옛 그래프로 구운 것 - 새 그래프 기준으로 재평가
    bank = json.loads((ROOT / "data/tag_combo/recipe_bank.json")
                      .read_text(encoding="utf-8"))["groups"]["1girl_solo"]
    hit_a = hit_r = rows = 0
    for anchor, recs in bank.items():
        if not recs:
            continue
        tags = recs[0]["tags"]
        rows += 1
        if any(frozenset((anchor, t)) in edges for t in tags):
            hit_a += 1
        if any(frozenset(p) in edges for p in combinations(tags, 2)):
            hit_r += 1
    print(f"\n=== 현재 뱅크(옛 그래프로 구움)를 새 그래프로 재평가 ===")
    print(f"   1위 행 {rows:,}개 중")
    print(f"   앵커와 접히는 후보가 낀 행  {hit_a:,} ({hit_a/rows:.1%})  <- 재채굴하면 사라진다")
    print(f"   행 안에 접히는 쌍이 있는 행 {hit_r:,} ({hit_r/rows:.1%})  <- 재채굴하면 사라진다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
