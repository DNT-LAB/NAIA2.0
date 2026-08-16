# -*- coding: utf-8 -*-
"""의미 중복 그래프 — 조합 한 줄에 같은 개념이 두 번 들어가지 않게 한다.

## 무엇이 문제였나

    feet, toes, soles              <- 한 칸을 세 번 쓴다
    weapon, holding weapon, holding sword
    pee, peeing self

현재 dedupe 는 **마지막 단어 일치 + 0.95 통계 함의**뿐이다(`core/tag_combo/query.py`).
실측으로 접어야 할 9쌍 중 2쌍만 잡는다.

## 왜 `siblings` 를 쓰면 안 되는가 (실측)

`interactive_tags.json` 의 `relations.siblings` 는 "같은 서랍에 든 것" 이라
**동일 개념이 아니라 대안**을 뜻한다. 그대로 접으면 오폭이 난다:

    접어야 8쌍 중 6쌍을 잡지만, **살려야 할 5쌍 중 3쌍을 죽인다**
    maid <-> apron, dress <-> apron, skirt <-> shirt  (전부 siblings)

`maid` 와 `apron` 은 정확히 같이 써야 하는 조합이다. siblings 로 접으면 이 기능이
낼 수 있는 가장 좋은 추천을 죽인다. 그래서 sibling 은 **단독 근거가 될 수 없고**,
같은 fine axis + 양방향 + 자카드/조건부확률 문턱을 **함께** 넘을 때만 쓴다.

## 계층 (위가 셀수록 강하다)

    1. wiki 공식 함의            무조건 접는다. 더 구체적인 쪽을 남긴다.
    2. 통계 near-entailment      한 방향 조건부 >= 0.95, support >= 30
    3. interactive parent/child  한 방향 조건부 >= 0.80, support >= 30
    4. 상호 sibling + 같은 축     자카드 >= 0.40 AND max 조건부 >= 0.70, support >= 60
    5. word_match                **단독 금지.** 다른 근거를 보강할 때만.

## 왜 union-find 를 쓰지 않는가

전이 폐쇄를 쓰면 중간의 넓은 태그 하나가 서로 무관한 두 개념을 접착한다
(`a-b` 강하고 `b-c` 강하다고 `a-c` 가 같은 개념은 아니다). **complete-link** 로
묶는다 - 무리 안의 **모든 쌍**이 문턱을 넘어야 한다.

## 순서 제약

이 그래프는 **응집 섬 탐색보다 먼저** 만들어야 한다. `feet/toes/soles` 는 NPMI
0.76~0.84 라, 중복을 접기 전에 섬을 찾으면 가장 강한 "가짜 섬" 으로 뽑힌다
(Codex 게이트).

## 쓰는 법

    python tools/build_semantic_graph.py --dry-run     # 경계 사례만 본다
    python tools/build_semantic_graph.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.tag_combo.model import ComboModel        # noqa: E402

# 셸이 죽은 환경에서는 preview 런처로 돌리는데, 프로세스가 끝나면 로그가 사라진다.
# 표준출력을 파일로도 남겨 Read 로 회수한다.
_LOG = ROOT / "data" / "tag_combo" / "_build_semantic_graph.log"
_BUF: list[str] = []
_real_print = print


def print(*a, **k):        # noqa: A001 - 의도적 shadow
    line = " ".join(str(x) for x in a)
    _BUF.append(line)
    _real_print(line, **k)


import atexit  # noqa: E402
atexit.register(lambda: _LOG.write_text("\n".join(_BUF), encoding="utf-8"))

# 판정이 옳은지 매 실행마다 확인하는 고정 사례. 하나라도 어긋나면 실패로 본다.
MUST_FOLD = [("weapon", "holding weapon"), ("pee", "peeing self"),
             ("long hair", "very long hair"), ("peeing", "peeing self")]
MUST_KEEP = [("dress", "apron"), ("maid", "apron"), ("skirt", "shirt"),
             ("thighhighs", "skirt"), ("blush", "sweat"),
             ("maid headdress", "apron"), ("smile", "open mouth")]


def load_axes() -> dict[str, set[str]]:
    """태그 -> 그 태그가 속한 fine axis 집합."""
    d = json.loads((ROOT / "data/interactive_axis_tags.json").read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for axis, tags in (d.get("axes") or {}).items():
        for t in tags:
            out.setdefault(str(t).strip().lower(), set()).add(axis)
    return out


def load_relations() -> dict[str, dict]:
    d = json.loads((ROOT / "data/interactive_tags.json").read_text(encoding="utf-8"))
    out = {}
    for tag, e in d.items():
        r = e.get("relations") or {}
        if not isinstance(r, dict):
            continue
        out[str(tag).strip().lower()] = {
            "parent": {str(r["parent"]).strip().lower()} if r.get("parent") else set(),
            "children": {str(x).strip().lower() for x in (r.get("children") or [])},
            "siblings": {str(x).strip().lower() for x in (r.get("siblings") or [])},
        }
    return out


class Stats:
    """조건부 확률·자카드를 모델 postings 로 계산한다."""

    def __init__(self, model: ComboModel):
        self.m = model
        self.n = max(1, model.header.posts)

    def post(self, t: str):
        i = self.m.tag_to_id.get(t)
        if i is None:
            return None
        return self.m._inv_posts[self.m._bounds[i]:self.m._bounds[i + 1]]

    def pair(self, a: str, b: str):
        pa, pb = self.post(a), self.post(b)
        if pa is None or pb is None or len(pa) == 0 or len(pb) == 0:
            return None
        inter = int(np.intersect1d(pa, pb, assume_unique=True).size)
        if inter == 0:
            return None
        union = len(pa) + len(pb) - inter
        return {"inter": inter, "a": len(pa), "b": len(pb),
                "conf_ab": inter / len(pa), "conf_ba": inter / len(pb),
                "jaccard": inter / union}


def decide(a: str, b: str, st: Stats, rel: dict, axes: dict,
           p, degenerate: frozenset[str] = frozenset()) -> tuple[bool, str, str]:
    """(접을까, 근거). 근거 문자열은 산출물에 남겨 나중에 감사할 수 있게 한다.

    근거 문자열의 첫 낱말이 **종류**다:
        `equivalent`  양방향 함의 - 어느 쪽을 남겨도 된다
        `implies`     한 방향 - **구체적인 쪽(specific)을 남긴다**
    `specific=<태그>` 조각이 붙어 소비자가 방향을 알 수 있다.
    """
    # **파티션 안에서 거의 항상 참인 태그는 함의 검사가 자명하게 통과한다.**
    # `1girl_solo` 모델에서 `1girl`/`solo` 는 P=1.0 이라 무엇과도 conf 1.000 이
    # 나오고, 그래서 `['1girl','1other','solo']` 라는 무리가 생겼다. 인원 태그를
    # 하나로 접으면 인원 판정이 무너진다 - 이건 개념 동일성이 아니라 파티션의
    # 정의다. 빈도가 극단적으로 높은 태그를 통째로 뺀다.
    if a in degenerate or b in degenerate:
        return False, "", ""
    s = st.pair(a, b)
    if s is None:
        return False, "", ""
    mx = max(s["conf_ab"], s["conf_ba"])
    ra, rb = rel.get(a, {}), rel.get(b, {})

    # 2. 통계 near-entailment
    #
    # ⚠️ **자카드 바닥이 반드시 함께 있어야 한다.** `max(conf)` 만 보면 희귀
    # 태그가 거대한 일반 태그를 **자명하게** 함의하는 것까지 접는다(Codex 감사,
    # 신규 간선 균등표본 120개 중 명백한 오폭 13개 = 10.8%):
    #
    #     breasts | strap lift          c=0.000/0.986  J=0.000  "파인 옷=가슴 있음"
    #     breasts | plunging neckline   c=0.002/0.956  J=0.002
    #     animal ears | horseshoe ornament c=0.003/0.961 J=0.003
    #     american flag dress | long hair c=0.962/0.001 J=0.001
    #
    # 이걸 접으면 **정보가 있는 쪽(`strap lift`)이 사라진다.** 진짜 동의는
    # 자카드가 높다: panties|underwear .814 · greyscale|monochrome .737 ·
    # street|road .490 · bandaged arm|bandages .413. 실측으로 좋은 접기 14개는
    # 최소 0.224 라 바닥 0.10 이면 전부 살고 극단 비대칭 5개가 죽는다.
    if (mx >= p.entail_conf and s["inter"] >= p.min_support
            and s["jaccard"] >= p.entail_jaccard):
        # **방향을 정한다.** `conf_ab = P(b|a)` 이므로, 그것이 1.0 이면 a 의
        # 게시물이 전부 b 를 갖는다 = **a 가 b 의 부분집합** = a 가 구체적이다.
        # 둘 다 높으면 동의어라 어느 쪽을 남겨도 된다.
        ab, ba = s["conf_ab"] >= p.entail_conf, s["conf_ba"] >= p.entail_conf
        if ab and ba:
            return True, "", f"equivalent conf={mx:.3f} J={s['jaccard']:.3f}"
        # ⚠️ 남길 쪽은 **별도 필드**로 돌려준다. 근거 문자열에 `specific=<태그>`
        # 로 넣었더니 `very long hair` 가 공백에서 잘려 `very` 가 됐다.
        return True, (a if ab else b), f"implies conf={mx:.3f} J={s['jaccard']:.3f}"

    # 3. interactive parent/child
    # 관계표가 방향을 이미 안다 - child 가 구체적이다.
    a_child = (b in ra.get("parent", ())) or (a in rb.get("children", ()))
    b_child = (a in rb.get("parent", ())) or (b in ra.get("children", ()))
    if (a_child or b_child) and mx >= p.pc_conf and s["inter"] >= p.min_support:
        spec = a if a_child else b
        return True, spec, f"implies conf={mx:.3f} src=parent/child"

    # 4. 상호 sibling + 같은 fine axis (**기본 꺼짐**)
    #
    # ❌ 이 층은 전수 감사에서 **6개 중 3개가 오폭**이었다(Codex):
    #     정상  feet|soles · feet|toes · soles|toes
    #     오폭  bow (music)|violin        활과 바이올린은 별개 물체
    #           eyewear on head|sunglasses 착용 위치와 물체
    #           cross-laced footwear|lace-up boots  끈 속성과 부츠 종류
    #
    # 통계로는 안 갈린다(오폭의 J 0.439~0.502 vs 정상 0.408~0.583). 같은 축
    # 조건도 셋 다 통과한다. 기대값이 0 에 가까운 층을 자동 접기에 두는 것은
    # 위험만 남기므로 껐다. `feet/toes/soles` 를 잃는 것이 대가다 -
    # 되살리려면 `--family` 를 주되, 그때는 오폭 3건도 같이 들어온다.
    if p.family:
        both_sib = (b in ra.get("siblings", ())) and (a in rb.get("siblings", ()))
        same_axis = bool(axes.get(a, set()) & axes.get(b, set()))
        if (both_sib and same_axis and s["jaccard"] >= p.sib_jaccard
                and mx >= p.sib_conf and s["inter"] >= p.sib_support):
            return True, "", f"family J={s['jaccard']:.3f} conf={mx:.3f}"
    return False, "", ""


def main() -> int:
    ap = argparse.ArgumentParser(description="의미 중복 그래프 생성")
    ap.add_argument("--model", default=str(ROOT / "data/tag_combo/1girl_solo.ncsr"),
                    help="통계 출처. 개념 동일성은 인원 수와 무관하므로 가장 큰 것 하나면 된다")
    ap.add_argument("--out", default=str(ROOT / "data/tag_combo/semantic_graph.json"))
    ap.add_argument("--entail-conf", type=float, default=0.95)
    ap.add_argument("--pc-conf", type=float, default=0.80)
    ap.add_argument("--entail-jaccard", type=float, default=0.10,
                    help="통계 함의에 거는 자카드 바닥. max(conf) 만으로는 희귀->일반 "
                         "자명 함의(breasts|strap lift, J=0.000)를 못 거른다")
    ap.add_argument("--family", action="store_true",
                    help="sibling 기반 접기를 켠다. 전수 감사 6개 중 3개 오폭이라 기본 꺼짐")
    ap.add_argument("--sib-jaccard", type=float, default=0.40)
    ap.add_argument("--sib-conf", type=float, default=0.70)
    ap.add_argument("--min-support", type=int, default=30)
    ap.add_argument("--sib-support", type=int, default=60)
    ap.add_argument("--degenerate-p", type=float, default=0.90,
                    help="이 확률 이상으로 흔한 태그는 함의 검사에서 뺀다. 파티션 정의 태그"
                         "(1girl/solo)가 무엇과도 conf 1.0 을 내는 것을 막는다")
    ap.add_argument("--neighbors", type=int, default=40,
                    help="태그마다 동시출현 상위 몇 개를 후보 쌍에 넣나. 함의는 "
                         "교집합이 큰 쪽에서만 성립하므로 이웃을 보면 충분하다")
    ap.add_argument("--neighbor-min", type=int, default=200,
                    help="이보다 드문 태그는 이웃 스캔에서 뺀다(비용/잡음)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    m = ComboModel(Path(args.model))
    m.ensure_inverted()
    st, rel, axes = Stats(m), load_relations(), load_axes()
    n = max(1, m.header.posts)
    degenerate = frozenset(t for i, t in enumerate(m.tags)
                           if m.freq[i] / n >= args.degenerate_p)
    print(f"모델 어휘 {len(m.tags):,} · 관계 {len(rel):,} · 축 매핑 {len(axes):,}")
    print(f"자명 태그 제외 {len(degenerate)}개 (P >= {args.degenerate_p}): "
          f"{sorted(degenerate)[:8]}")

    print("\n=== 고정 사례 판정 ===")
    ok = True
    for label, cases, want in (("접어야", MUST_FOLD, True), ("살려야", MUST_KEEP, False)):
        for a, b in cases:
            got, spec_t, why = decide(a, b, st, rel, axes, args, degenerate)
            mark = "OK " if got == want else "!! "
            if got != want:
                ok = False
            s = st.pair(a, b)
            det = (f"J={s['jaccard']:.3f} conf={max(s['conf_ab'], s['conf_ba']):.3f}"
                   if s else "(교집합 없음)")
            print(f"   {mark}{label}: {a:<16} {b:<18} {det:<28} {why or '-'}")
    print("\n고정 사례 " + ("전부 통과" if ok else "**실패 — 문턱을 다시 봐라**"))

    if args.dry_run:
        return 0 if ok else 1

    # ---- 후보 쌍 ------------------------------------------------------
    #
    # ⚠️ **관계표로만 좁히면 안 된다.** 처음엔 `interactive_tags.json` 의
    # parent/children/siblings 로 연결된 쌍만 후보로 삼았는데(288,580쌍),
    # 통계 함의는 관계 유무와 무관하다. 실측으로 이런 것들이 **평가조차 안 됐다**:
    #
    #     panties  | underwear   c=1.000   관계 항목 없음 -> 후보 아님 -> 간선 없음
    #     dildo    | sex toy     c=1.000
    #     greyscale| monochrome  c=1.000
    #     hairclip | hair ornament c=1.000
    #
    # 그 결과 1위 행의 **18.2%** 가 앵커와 conf>=0.95 인 후보를 달고 있었고,
    # **15.2%** 는 행 안에 그런 쌍이 있었다(Codex 라운드 1 진단).
    #
    # 전 어휘 쌍은 8,700만이라 불가능하다. 대신 **각 태그의 상위 동시출현 이웃**을
    # 후보로 넣는다 - 함의는 정의상 교집합이 큰 쪽에서만 성립하므로, 이웃을
    # 놓치는 함의는 없다.
    t0 = time.time()
    known = set(m.tags)
    cand: set[tuple[str, str]] = set()
    for t, r in rel.items():
        if t not in known:
            continue
        for other in (r["parent"] | r["children"] | r["siblings"]):
            if other in known and other != t:
                cand.add(tuple(sorted((t, other))))
    n_rel = len(cand)

    ip, ix = m.indptr, m.indices
    for i, t in enumerate(m.tags):
        if m.freq[i] < args.neighbor_min:
            continue
        p = m._inv_posts[m._bounds[i]:m._bounds[i + 1]]
        cnt = np.bincount(
            np.concatenate([ix[ip[x]:ip[x + 1]] for x in p]).astype(np.int64),
            minlength=m.header.vocab)
        # 자기 자신 제외, 교집합 상위 K
        cnt[i] = 0
        for j in np.argpartition(-cnt, min(args.neighbors, len(cnt) - 1))[:args.neighbors]:
            if cnt[j] >= args.min_support:
                cand.add(tuple(sorted((t, m.tags[int(j)]))))
    print(f"\n후보 쌍 {len(cand):,} (관계표 {n_rel:,} + 동시출현 이웃 "
          f"상위 {args.neighbors})")

    edges = []
    for a, b in cand:
        got, spec_t, why = decide(a, b, st, rel, axes, args, degenerate)
        if got:
            edges.append({"a": a, "b": b, "keep": spec_t, "why": why})
    print(f"접기 간선 {len(edges):,} · {time.time()-t0:.0f}s")

    # complete-link 무리 만들기 - 모든 쌍이 간선이어야 한 무리다.
    adj: dict[str, set[str]] = {}
    for e in edges:
        adj.setdefault(e["a"], set()).add(e["b"])
        adj.setdefault(e["b"], set()).add(e["a"])
    clusters, seen = [], set()
    for t in sorted(adj, key=lambda x: -len(adj[x])):
        if t in seen:
            continue
        group = [t]
        for c in sorted(adj[t], key=lambda x: -len(adj.get(x, ()))):
            if c in seen:
                continue
            if all(c in adj.get(g, ()) for g in group):     # complete-link
                group.append(c)
        if len(group) > 1:
            clusters.append(sorted(group))
            seen |= set(group)
    print(f"무리 {len(clusters):,} · 최대 크기 {max((len(c) for c in clusters), default=0)}")

    out = Path(args.out)
    out.write_text(json.dumps({
        "format": "NSG1",
        "policy": {k: getattr(args, k) for k in
                   ("entail_conf", "pc_conf", "sib_jaccard", "sib_conf",
                    "min_support", "sib_support")},
        "edges": edges, "clusters": clusters,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"저장: {out}  ({out.stat().st_size/1e6:.1f}MB)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
