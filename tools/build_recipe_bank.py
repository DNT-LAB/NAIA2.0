# -*- coding: utf-8 -*-
"""레시피 뱅크 — 앵커별 2/3태그 조합을 **오프라인 전수**로 캔다.

## 무엇을 대체하는가

런타임 `query.py:_tally` 는 게시물 하나당 **정확히 한 묶음만** 지명한다(그 게시물의
후보를 lift 로 정렬해 상위 3개). 그래서 흔하면서 적합한 태그는 한 번도 세어지지
않는다. 실측:

    embarrassed 기준 blush: 교집합 8,390/9,586 (conf 0.875, lift 2.25)
      -> K=3 지명 0회, K=6 지명 0회.  **한 번도 후보 묶음에 못 들어간다**

세어졌다면 이겼다:
    ['blush','nose blush','sweat']  지지 468 -> score 1,732
    ['peeing','pee','peeing self']  지지  79 -> score   394

## 왜 P(B) 상한을 없앴는가

기존 후보 게이트에는 `P(B) <= 0.30` 이 있었다. `blush` 는 P=0.388 이라 여기서
잘린다. 배경 태그를 막으려던 것인데 **흔한 정답까지 같이 막았다.** 문턱을 확률이
아니라 **lift** 로 바꾸면 갈린다(실측, embarrassed 기준):

    blush              P=.388  lift 2.25   <- 살아야 한다
    breasts            P=.546  lift 1.30
    looking at viewer  P=.618  lift 1.15   <- 배경
    long hair          P=.584  lift 1.05   <- 배경

## 왜 lift 상위로 자르지 않는가

후보를 lift 상위 N 으로 자르면 `blush`(2.25)가 `peeing`(20.8) 류에 밀려 또
사라진다. **전수 pair 를 먼저 계산하고, 역할(의상/신체/표정/기타)별 쿼터**로
자른다(Codex 게이트). 그래야 각 역할의 대표가 살아남는다.

## 순서

    1. 의미 중복 그래프   (build_semantic_graph.py)   <- 먼저
    2. 이 도구
    3. head/최종 캐시     (맨 마지막)

## 쓰는 법

    python tools/build_recipe_bank.py --group 1girl_solo --limit 50 --dry-run
    python tools/build_recipe_bank.py
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.tag_combo.model import ComboModel        # noqa: E402
from core.tag_combo.noise import is_color_tag, is_framing_tag   # noqa: E402
from core.tag_combo.person import PERSON_GROUPS    # noqa: E402

ROLES = ("clothing", "body", "action", "other")

# uint8 값별 1비트 수. 비트셋 교집합의 크기를 LUT 합으로 얻는다.
_POPCOUNT = np.unpackbits(np.arange(256, dtype=np.uint8)[:, None], axis=1).sum(1).astype(np.int32)


def load_roles() -> dict[str, str]:
    """태그 -> 역할. fine axis 접두사로 가른다.

    Event Preset 의 `tag_category` 는 clothing/event/expression/color/other 뿐이라
    신체(characteristic)를 못 가른다. 축 접두사가 더 촘촘하다(127축).
    """
    d = json.loads((ROOT / "data/interactive_axis_tags.json").read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for axis, tags in (d.get("axes") or {}).items():
        a = axis.lower()
        if a.startswith("cloth"):
            r = "clothing"
        elif a.startswith(("body", "face", "hair", "expr", "skin")):
            r = "body"
        elif a.startswith(("pose", "act", "verb", "gaze", "hand")):
            r = "action"
        else:
            r = "other"
        for t in tags:
            out.setdefault(str(t).strip().lower(), r)
    return out


def load_folds(path: Path) -> tuple[set[frozenset[str]], dict[frozenset[str], str]]:
    """(접히는 쌍, 그 쌍에서 **남길 쪽**).

    ⚠️ 예전엔 `frozenset` 만 돌려줘서 **방향을 잃었다**(Codex 지적). 그러면
    `white dress` + `dress` 를 접을 때 어느 쪽이 남는지가 순회 순서로 정해진다 -
    정보가 있는 `white dress` 가 버려질 수 있다. 그래프가 `implies specific=...`
    로 방향을 주므로 그걸 그대로 쓴다. `equivalent` 는 방향이 없어 빈 값이다.
    """
    if not path.exists():
        return set(), {}
    g = json.loads(path.read_text(encoding="utf-8"))
    pairs, keep = set(), {}
    for e in (g.get("edges") or []):
        k = frozenset((e["a"], e["b"]))
        pairs.add(k)
        if e.get("keep"):
            keep[k] = e["keep"]
    return pairs, keep


def mine_anchor(m: ComboModel, anchor: str, *, folds, roles, p, keep_side=None) -> dict:
    keep_side = keep_side or {}
    ai = m.tag_to_id.get(anchor)
    if ai is None:
        return {}
    posts = m._inv_posts[m._bounds[ai]:m._bounds[ai + 1]]
    n = len(posts)
    if n < p.min_anchor:
        return {}

    # ---- 1. 전수 pair -------------------------------------------------
    # **파이썬 루프로 원소마다 증가시키면 안 된다.** 처음엔 게시물마다
    # `cnt[row] += 1` 을 돌렸는데 앵커 40개에 39초였다(13그룹 환산 20시간+).
    # bincount 로 세면 같은 값을 훨씬 싸게 얻는다. 한 번에 이어 붙이지 않는
    # 이유는 `ComboModel.tag_counts` 주석에 있다(전 코퍼스에서 앵커 하나가
    # 1.1GB 를 먹었다).
    cnt = m.tag_counts(posts)
    prob = m.freq / max(1, m.header.posts)
    with np.errstate(divide="ignore", invalid="ignore"):
        lift = np.where(prob > 0, (cnt / n) / np.maximum(prob, 1e-12), 0.0)
    # **후보 문턱과 묶음 지지도를 분리한다.**
    #
    # `min_pair=30` 은 튜플 지지도를 위한 **절대 개수**다. 그걸 후보 문턱에도
    # 쓰면 작은 앵커가 통째로 죽는다 - n=80 인 앵커는 후보가 37.5% 이상 겹쳐야
    # 통과한다. 평면 목록은 itemset 지지도가 필요 없는데 itemset 용 문턱에
    # 갇혀 있었다(Codex 지적 2026-08-17).
    #
    # `min(min_pair, max(floor, ceil(ratio*n)))` 은 **내리기만 한다**: 큰 앵커는
    # 30 그대로, 작은 앵커만 완화된다. 순수 비율(0.10*n)을 전체에 적용하면 큰
    # 앵커의 바가 올라가 기존 뱅크에서 93,934칩·250앵커가 날아간다(Codex 실측).
    # 회복 밴드 2,986종 기준 절대 30 은 2,937개, 비율은 2,986개를 살린다.
    #
    # 절대 개수는 **증거량**, 비율은 **앵커 관련성**이다. 하나로 둘을 표현하면
    # 안 된다. 묶음 지지도(아래 tally)는 절대 `min_pair` 를 그대로 쓴다.
    cand_thr = min(p.min_pair, max(p.cand_floor, math.ceil(p.cand_ratio * n)))
    ok = np.where((cnt >= cand_thr) & (lift >= p.min_lift))[0]

    cands = []
    for c in ok:
        t = m.tags[int(c)]
        # 색·무늬와 **구도/판/메타**를 뺀다. 둘 다 "그림을 어떻게 만들었나" 지
        # 무엇이 들었나가 아니다. 자세 축이 특히 이걸로 오염됐다(실측: 자세 앵커
        # 칩의 4.1% 가 프레이밍, 의상은 1.9%).
        if t == anchor or is_color_tag(t) or is_framing_tag(t):
            continue
        if frozenset((t, anchor)) in folds:      # 앵커와 같은 개념이면 뺀다
            continue
        cands.append((int(c), t, float(lift[c]), int(cnt[c])))
    if len(cands) < 2:
        return {}

    # ---- 2. 역할별 쿼터 ------------------------------------------------
    # ⚠️ **lift 는 게이트, 지지도는 순위.** 처음엔 역할 안에서도 lift 순으로
    # 잘랐는데, 그게 Codex 가 경고한 실수를 역할 안에서 그대로 반복했다. 실측:
    #
    #   sword 앵커 · holding 은 66.1% 에 lift 3.36 인데, sword 전용 희귀 태그
    #   (unsheathing/scabbard, lift 38)에 밀려 action 쿼터 8위 밖으로 나갔다.
    #   그 결과 1위가 `scabbard, unsheathed` **0.69%** 로, 고치기 전(27.6%)보다
    #   훨씬 나빠졌다.
    #
    # lift 문턱이 이미 배경을 걷어냈으니, 남은 것 중에서는 **흔한 것**을 남긴다.
    by_role: dict[str, list] = {r: [] for r in ROLES}
    for c, t, lf, ct in sorted(cands, key=lambda x: -x[3]):
        by_role[roles.get(t, "other")].append((c, t, lf, ct))
    picked = [x for r in ROLES for x in by_role[r][:p.role_quota]]
    if len(picked) < 2:
        return {}
    keep_ids = {c for c, _, _, _ in picked}
    name = {c: t for c, t, _, _ in picked}

    # ---- 3. 제한된 후보 안에서 2/3-itemset 전수 ------------------------
    # 게시물 x 후보 불리언 행렬을 세우고 **행렬곱**으로 센다. 게시물마다
    # `combinations` 를 돌리는 파이썬 루프가 두 번째 병목이었다.
    # **비트셋 + popcount.** 처음엔 게시물 x 후보 정수 행렬을 만들어 `Mi.T @ Mi`
    # 로 쌍을 세고, 3-itemset 은 쌍마다 `both @ Mi` 를 돌렸다. 후보 32개면 쌍이
    # 496개라 494k x 32 matvec 을 496번 = 80억 연산이고, 실측으로 앵커 12개에
    # 26초였다(13그룹 환산 수십 시간). 열을 비트로 눌러 담으면 교집합이 AND
    # 한 번 + 바이트 popcount 합이라 같은 답을 수백 배 싸게 얻는다.
    cols = sorted(keep_ids)
    k = len(cols)
    bits = np.zeros((k, (n + 7) // 8), dtype=np.uint8)
    for j, c in enumerate(cols):
        cp = m._inv_posts[m._bounds[c]:m._bounds[c + 1]]
        common = np.intersect1d(posts, cp, assume_unique=True)
        if common.size:
            col = np.zeros(n, dtype=bool)
            col[np.searchsorted(posts, common)] = True
            bits[j] = np.packbits(col)
    popc = _POPCOUNT

    tally: Counter = Counter()
    inter2: dict[tuple[int, int], np.ndarray] = {}
    for i in range(k):
        for j in range(i + 1, k):
            ab = bits[i] & bits[j]
            v = int(popc[ab].sum())
            if v >= p.min_pair:
                tally[(cols[i], cols[j])] = v
                inter2[(i, j)] = ab
    for (i, j), ab in inter2.items():
        for x in range(j + 1, k):
            v = int(popc[ab & bits[x]].sum())
            if v >= p.min_pair:
                tally[tuple(sorted((cols[i], cols[j], cols[x])))] = v

    # ---- 3.5 평면 태그 목록 -------------------------------------------
    #
    # 화면은 묶음 4줄 대신 **태그 + % 나열**로 간다(사용자 결정 2026-08-16).
    # 묶음 표시는 같은 태그가 여러 줄에 나와 반복으로 읽혔고(`curvy` 2회 ·
    # `ass` 2회), 가로 공간도 크게 남았다.
    #
    # ⚠️ **여기 쓰는 %는 묶음 커버리지가 아니라 `P(태그|앵커)` 다.** 묶음
    # 커버리지를 태그별로 쓰면 거짓말이 된다 - `embarrassed`+`blush` 는 묶음
    # 기준 19% 지만 실제 조건부는 **88%** 다. 묶음 확률은 세 태그가 동시에 나올
    # 확률이라 태그 하나의 빈도와 다르다.
    flat = [{"tag": t, "p": round(ct / n, 4), "lift": round(lf, 2)}
            for _, t, lf, ct in sorted(picked, key=lambda x: -x[3])][:p.flat_top]

    surp = -np.log2(np.maximum(prob, 1e-12))
    out = []
    for combo, sup in tally.most_common(p.per_anchor * 8):
        if sup < p.min_pair:
            break
        tags = [name[c] for c in combo]
        # 행 안 의미 중복 제거.
        #
        # **방향을 존중한다.** 접히는 쌍을 만나면 그래프가 지정한 구체적인 쪽을
        # 남긴다 - 순회 순서로 정하면 `white dress` 대신 `dress` 가 남을 수 있다.
        kept: list[str] = []
        for t in tags:
            clash = next((k for k in kept if frozenset((t, k)) in folds), None)
            if clash is None:
                kept.append(t)
                continue
            spec = keep_side.get(frozenset((t, clash)))
            if spec == t:                      # 새로 온 쪽이 더 구체적이다
                kept[kept.index(clash)] = t
        if len(kept) != len(tags):
            continue
        cov = sup / n
        s = float(sum(surp[c] for c in combo))
        out.append({"tags": tags, "support": sup, "coverage": round(cov, 4),
                    "score": round(sup * math.log2(1 + s), 1)})
    out.sort(key=lambda x: -x["score"])
    return {"rows": out[:p.per_anchor], "tags": flat}


def main() -> int:
    ap = argparse.ArgumentParser(description="레시피 뱅크 (오프라인 frequent itemset)")
    ap.add_argument("--models", default=str(ROOT / "data/tag_combo"))
    ap.add_argument("--graph", default=str(ROOT / "data/tag_combo/semantic_graph.json"))
    ap.add_argument("--out", default=str(ROOT / "data/tag_combo/recipe_bank.json"))
    ap.add_argument("--group", default="", help="한 그룹만 (비면 13개 전부)")
    ap.add_argument("--limit", type=int, default=0, help="앵커 수 상한(시험용)")
    # ⚠️ **기본값은 실제로 구운 값이어야 한다.** 배포한 v3 는 `80 / 2.0` 으로
    # 구웠는데 기본값은 한동안 `200 / 1.3` 이었다 - 인자 없이 다시 돌리면 다른
    # 뱅크가 나온다(Codex 지적). 재현 불가능한 산출물은 산출물이 아니다.
    #   min_anchor 200 -> 80: 축 답변율 중앙 36.8% -> 50.0%
    #   min_lift  1.3 -> 2.0: 공통 배경을 먼저 거른다(표시 칩 lift 중앙 4.0)
    ap.add_argument("--min-anchor", type=int, default=80, help="앵커 최소 게시물")
    ap.add_argument("--min-pair", type=int, default=30,
                    help="2/3-itemset 지지도 하한(절대 개수). 후보 문턱과 별개다")
    ap.add_argument("--cand-ratio", type=float, default=0.10,
                    help="후보 문턱의 앵커 대비 비율. 작은 앵커만 완화된다")
    ap.add_argument("--cand-floor", type=int, default=10,
                    help="후보 문턱의 절대 하한. 이보다 낮게는 안 내려간다")
    ap.add_argument("--min-lift", type=float, default=2.0,
                    help="배경 태그 컷. long hair 1.05 / looking at viewer 1.15 는 죽고 "
                         "blush 2.25 는 산다")
    ap.add_argument("--role-quota", type=int, default=8)
    ap.add_argument("--flat-top", type=int, default=16,
                    help="앵커당 평면 태그 목록 길이. 화면은 이 중 앞쪽만 쓴다")
    ap.add_argument("--per-anchor", type=int, default=12)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    folds, keep_side = load_folds(Path(args.graph))
    roles = load_roles()
    print(f"접기 간선 {len(folds):,} (방향 있는 것 {len(keep_side):,}) "
          f"· 역할 매핑 {len(roles):,}")
    groups = [args.group] if args.group else list(PERSON_GROUPS)
    bank: dict[str, dict] = {}
    t0 = time.time()

    # ⚠️ **13그룹 완전성을 빌드에서 강제한다.**
    #
    # 예전엔 모델이 없는 그룹을 조용히 건너뛰었다. 그건 런타임에 "뱅크에 이
    # 그룹이 없으면 온라인 폴백" 계약과 짝이었는데, 이제 배포에는 모델이 안
    # 가므로 폴백이 없다 - 부분 뱅크를 올리면 그 인원 그룹은 **통째로 죽는다**.
    # 조용한 부분 산출물보다 여기서 죽는 것이 낫다(Codex 지적 2026-08-17).
    # 한 그룹만 시험할 때는 `--group` 을 명시하라.
    if not args.group:
        gone = [g for g in groups if not (Path(args.models) / f"{g}.ncsr").exists()]
        if gone:
            print(f"!! 모델이 없는 그룹 {len(gone)}개: {gone}")
            print("   전량 배포 뱅크는 13그룹이 다 있어야 한다. "
                  "python tools/build_tag_combo_models.py")
            return 2

    for g in groups:
        p = Path(args.models) / f"{g}.ncsr"
        if not p.exists():
            print(f"   {g:<30} 모델 없음 (--group 지정이므로 건너뜀)")
            continue
        m = ComboModel(p)
        m.ensure_inverted()
        n = max(1, m.header.posts)
        anchors = [t for i, t in enumerate(m.tags)
                   if m.freq[i] >= args.min_anchor and m.freq[i] / n < 0.9
                   and not is_color_tag(t)]
        if args.limit:
            anchors = anchors[:args.limit]
        g0, done = time.time(), {}
        for a in anchors:
            r = mine_anchor(m, a, folds=folds, roles=roles, p=args, keep_side=keep_side)
            if r:
                done[a] = r
        bank[g] = done
        el = time.time() - g0
        print(f"   {g:<30} 앵커 {len(anchors):>6,} -> 레시피 있는 앵커 {len(done):>6,} "
              f"· {el:>6.0f}s")
        del m

    # 모델이 있어도 앵커가 0개면 결과는 같다 - 그 그룹은 통째로 죽는다.
    if not args.group:
        empty = sorted(g for g in groups if not bank.get(g))
        if empty:
            print(f"!! 앵커가 하나도 안 나온 그룹 {len(empty)}개: {empty}")
            print("   게이트가 너무 빡빡하거나 모델이 비었다. 쓰지 않고 멈춘다.")
            return 2

    tot = sum(len(v) for v in bank.values())
    rows = sum(len(r.get("rows") or []) for v in bank.values() for r in v.values())
    flats = sum(len(r.get("tags") or []) for v in bank.values() for r in v.values())
    print(f"평면 태그 {flats:,}개 (앵커당 평균 {flats/max(1,tot):.1f})")
    blob = json.dumps({"format": "NRB3", "policy": {
        # `flat_top` 도 남긴다 - 평면 목록 길이를 결정하는데 기록이 없으면
        # 산출물만 보고 어떤 설정으로 구웠는지 알 수 없다.
        k: getattr(args, k) for k in ("min_anchor", "min_pair", "min_lift",
                                      "role_quota", "per_anchor", "flat_top",
                                      "cand_ratio", "cand_floor")},
        "groups": bank}, ensure_ascii=False, separators=(",", ":"))
    import zlib
    print(f"\n앵커 {tot:,} · 레시피 {rows:,} · {time.time()-t0:.0f}s")
    print(f"JSON {len(blob.encode('utf-8'))/1e6:.1f}MB · "
          f"deflate {len(zlib.compress(blob.encode('utf-8'), 6))/1e6:.1f}MB")
    if args.dry_run:
        return 0
    Path(args.out).write_text(blob, encoding="utf-8")
    print(f"저장: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
