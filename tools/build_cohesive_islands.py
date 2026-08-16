# -*- coding: utf-8 -*-
"""응집 섬 — 사용자의 태그 뭉치 중 **의미가 뭉쳐 있는 것**을 앵커로 고른다.

## 왜

현재 백오프는 "최대 정보 부분집합" 을 고르는데, 그게 사실상 **가장 희귀한 태그
하나**로 수렴한다. 캐릭터 12태그를 주면 이렇게 된다(실측):

    [embarrassed, long hair, blue eyes, shaded face, sweatdrop, sweat,
     large breasts, garter belt, underwear, maid headdress, maid, apron]
      -> usedPrompt = ['shaded face']          <- maid/apron/embarrassed 를 다 버렸다
      -> greyscale, spot color, comic          <- 의미 중심이 사라진 결과

빈도로 고르는 것도 답이 아니다. 3-조합 중 **결합빈도 1위가 최악**을 냈다:

    long hair+blue eyes+large breasts (27,844장) -> flag print, american flag  0.22%
    maid+apron+maid headdress          (7,559장) -> black dress, maid apron    3.39%

기준은 빈도가 아니라 **응집도**다. 최약 pair NPMI 로 갈린다:

    maid+apron+headdress        최약 NPMI 0.679   (독립 대비 907배)
    dress+apron                            0.206
    embarrassed+blush                      0.178
    standing+shoes                         0.165
    kneeling+shoes                         0.045
    long hair+blue eyes+breasts            0.0099 (1.16배)

## 문턱

최약 pair NPMI >= 0.15. `.679` 는 매우 강한 maid 사례의 값이라 문턱으로 쓰면
거의 모든 것이 탈락한다. `.15` 는 위 대조군에서 **일반 외형 묶음(.010~.045)과
유효한 약한 조합(.165~.206) 사이**를 가른다(Codex 제안 + 여기서 재확인).

## 순서 제약

**의미 중복 그래프를 먼저 적용한다.** `feet/toes/soles` 는 NPMI 0.76~0.84 라,
접기 전에 섬을 찾으면 가장 강한 "가짜 섬" 으로 뽑힌다. 개념 단위로 접은 뒤에 센다.

## 쓰는 법

    python tools/build_cohesive_islands.py --check     # 대조군만 재본다
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.tag_combo.model import ComboModel        # noqa: E402

# 문턱이 옳은지 매 실행 확인하는 대조군. (태그들, 섬인가)
CONTROLS = [
    (["maid", "apron", "maid headdress"], True),
    (["serafuku", "neckerchief", "school uniform"], True),
    (["dress", "apron"], True),
    (["embarrassed", "blush"], True),
    (["long hair", "blue eyes", "large breasts"], False),
    (["long hair", "blue eyes"], False),
    (["sitting", "large breasts"], False),
    (["kneeling", "shoes"], False),
]


class Cohesion:
    def __init__(self, m: ComboModel, folds: set | None = None):
        self.m = m
        self.n = max(1, m.header.posts)
        self.fold = folds or set()

    def post(self, t: str):
        i = self.m.tag_to_id.get(t)
        return None if i is None else self.m._inv_posts[self.m._bounds[i]:self.m._bounds[i + 1]]

    def npmi(self, a: str, b: str) -> tuple[float, int]:
        """정규화 PMI. -1(배타) ~ 0(독립) ~ +1(항상 동시)."""
        pa, pb = self.post(a), self.post(b)
        if pa is None or pb is None or len(pa) == 0 or len(pb) == 0:
            return -1.0, 0
        inter = int(np.intersect1d(pa, pb, assume_unique=True).size)
        if inter == 0:
            return -1.0, 0
        p_ab = inter / self.n
        p_a, p_b = len(pa) / self.n, len(pb) / self.n
        pmi = math.log(p_ab / (p_a * p_b))
        return pmi / (-math.log(p_ab)), inter

    def weakest(self, tags: list[str]) -> tuple[float, int]:
        """섬의 강도 = **가장 약한 쌍**. 하나라도 약하면 섬이 아니다."""
        if len(tags) < 2:
            return -1.0, 0
        vals = [self.npmi(a, b) for a, b in combinations(tags, 2)]
        return min(v for v, _ in vals), min(n for _, n in vals)

    def concepts(self, tags: list[str]) -> list[str]:
        """의미 중복을 접어 개념 단위로 만든다.

        ⚠️ **무리(cluster) 가 아니라 간선(edge) 으로 접는다.** complete-link 무리는
        보수적이라 `weapon`-`holding weapon` 처럼 직접 간선이 있어도 서로 다른
        무리에 들어간다. 그러면 접기 후에도 둘이 남아 NPMI 0.844 짜리 **가짜 섬**이
        된다. 앞에서부터 남기되 이미 남긴 것과 간선이 있으면 버린다.
        """
        out: list[str] = []
        for t in tags:
            if not any(frozenset((t, k)) in self.fold for k in out):
                out.append(t)
        return out


def load_folds(path: Path) -> set[frozenset[str]]:
    """접기 간선 집합. semantic_graph.json 의 edges 를 쓴다(clusters 가 아니라)."""
    if not path.exists():
        return set()
    g = json.loads(path.read_text(encoding="utf-8"))
    return {frozenset((e["a"], e["b"])) for e in (g.get("edges") or [])}


def main() -> int:
    ap = argparse.ArgumentParser(description="응집 섬 문턱 확인/생성")
    ap.add_argument("--model", default=str(ROOT / "data/tag_combo/1girl_solo.ncsr"))
    ap.add_argument("--graph", default=str(ROOT / "data/tag_combo/semantic_graph.json"))
    ap.add_argument("--min-npmi", type=float, default=0.15)
    ap.add_argument("--min-pair", type=int, default=30)
    ap.add_argument("--check", action="store_true", help="대조군만 재고 끝낸다")
    args = ap.parse_args()

    m = ComboModel(Path(args.model))
    m.ensure_inverted()
    folds = load_folds(Path(args.graph))
    co = Cohesion(m, folds)
    print(f"어휘 {len(m.tags):,} · 접기 사전 {len(folds):,}")

    print(f"\n=== 대조군 (문턱 NPMI >= {args.min_npmi}, 최소 쌍 {args.min_pair}) ===")
    ok = True
    for tags, want in CONTROLS:
        con = co.concepts(tags)
        w, n = co.weakest(con)
        got = (w >= args.min_npmi) and (n >= args.min_pair)
        if got != want:
            ok = False
        note = f" (접기: {tags} -> {con})" if con != tags else ""
        print(f"   {'OK ' if got == want else '!! '}{str(tags):<52} "
              f"최약 NPMI {w:>6.3f} 쌍 {n:>6,} -> {'섬' if got else '아님':<4}{note}")

    print("\n=== 접기 전/후 비교 (가짜 섬이 걸러지는가) ===")
    for tags in (["feet", "toes", "soles"], ["weapon", "holding weapon", "holding sword"]):
        w0, _ = co.weakest(tags)
        con = co.concepts(tags)
        w1, _ = co.weakest(con) if len(con) > 1 else (-1.0, 0)
        print(f"   {str(tags):<48} 접기전 {w0:>6.3f} -> 접은 뒤 {con} "
              f"{'(단일 개념, 섬 아님)' if len(con) < 2 else f'{w1:.3f}'}")

    print("\n대조군 " + ("전부 통과" if ok else "**실패 — 문턱을 다시 봐라**"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
