# -*- coding: utf-8 -*-
"""동반 후보에서 **특정 캐릭터의 디자인**을 걷어낸다.

## 무엇을 고치려는 것인가

출처를 게시물 원본으로 바꾼 뒤 오분류율이 7.5% -> 3.12% 로 떨어졌는데, 남은 261건 중
**187건(72%)이 `chara`** 다. 그런데 이건 분류로는 못 잡는다 — 후보가
`horse ears`(11회) · `side ponytail` · `pink hair` · `twintails` 처럼 전부 평범한
`Person_Body/hair_styles` 태그다. 인기 캐릭터 한 명이 그 머리·귀를 갖고 있어서
통계가 그 캐릭터를 반영하는 것이지, 태그 자체가 캐릭터 태그가 아니다.

**신호는 게시물의 `character` 열에 있다.** 어떤 동반이 한 캐릭터에 몰려 있으면
그건 태그 사이의 관계가 아니라 그 캐릭터의 디자인이다:

    twintails + horse ears  ->  우마무스메 한 명이 대부분
    beach + swimsuit        ->  수천 캐릭터에 고루 퍼진다

`character` 열은 게시물의 89% 에 채워져 있고 샤드 하나에 고유 캐릭터가 2만 개다.
(이 열은 **후보 어휘로는 절대 쓰지 않는다** — `medallion -> oda uri` 같은 오분류의
출처다. 판정에만 쓴다. 두 용도를 섞지 마라.)

## 왜 별도 도구인가

빌더는 어휘 전체의 희소행렬로 돌아서 게시물 단위 정보에 접근하지 않는다. 그래서
빌더가 상위 12개까지 덤프해 두면(`--dump-tags`), 이 도구가 게시물을 한 번 훑어
집중도를 재고 **살아남은 것 중 상위 4개**를 고른다. 탈락분은 차순위로 메워진다.

## 쓰는 법

    python tools/filter_character_bias.py --eval          # 문턱 sweep + 골드 채점
    python tools/filter_character_bias.py                 # 사전에 반영
"""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

CO = Path("data/tag_cooccurrence.json")
CAND = Path("data/_companion_review/candidates.json")
POOL = Path("data/tag_pool_120_139.parquet")
GOLD = Path("data/tag_companion_goldset.json")


def main() -> int:
    ap = argparse.ArgumentParser(description="캐릭터 집중도로 동반 후보 거르기")
    ap.add_argument("--pool", default=str(POOL))
    ap.add_argument("--candidates", default=str(CAND))
    ap.add_argument("--top", type=int, default=4)
    ap.add_argument("--max-share", type=float, default=0.5,
                    help="한 캐릭터가 동반 게시물의 이 비율을 넘게 차지하면 버린다")
    ap.add_argument("--min-pair", type=int, default=8,
                    help="동반 게시물이 이보다 적으면 집중도를 못 믿는다 — 판정을 보류한다")
    ap.add_argument("--eval", action="store_true", help="문턱 sweep 만 하고 쓰지 않는다")
    args = ap.parse_args()

    cand = json.loads(Path(args.candidates).read_text(encoding="utf-8"))["candidates"]
    doc = json.loads(CO.read_text(encoding="utf-8"))
    print(f"후보 덤프 {len(cand)}태그 / 간선 {sum(len(v) for v in cand.values()):,}")

    # 대상 -> 후보 집합. 게시물 한 건에서 확인할 쌍만 남긴다.
    want: dict[str, set[str]] = {t: {c["tag"] for c in cs} for t, cs in cand.items()}
    targets = set(want)

    # ── 게시물 한 번 훑기: 쌍마다 동반 수와 캐릭터 분포 ───────────────────────
    pair_n: Counter[tuple[str, str]] = Counter()
    pair_ch: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    n = 0
    for batch in pq.ParquetFile(args.pool).iter_batches(
            batch_size=100_000, columns=["general", "character"]):
        gen = batch.column(0).to_pylist()
        chs = batch.column(1).to_pylist()
        for g, ch in zip(gen, chs):
            if not g:
                continue
            n += 1
            u = {x.strip().lower() for x in str(g).split(",") if x.strip()}
            hit = u & targets
            if not hit:
                continue
            # 캐릭터가 여러 명이면 그 게시물은 어느 한 명의 것이 아니다 —
            # 집중도를 재는 목적상 '복수' 는 편향의 증거가 아니므로 따로 센다.
            names = [x.strip() for x in str(ch or "").split(",") if x.strip()]
            key = names[0] if len(names) == 1 else ""
            for a in hit:
                for b in (want[a] & u):
                    if b == a:
                        continue
                    pair_n[(a, b)] += 1
                    if key:
                        pair_ch[(a, b)][key] += 1
    print(f"게시물 {n:,} / 계측한 쌍 {len(pair_n):,}")

    def share(a: str, b: str) -> float:
        """동반 게시물 중 한 캐릭터가 차지하는 최대 비율. 표본이 적으면 0(판정 보류)."""
        tot = pair_n.get((a, b), 0)
        if tot < args.min_pair:
            return 0.0
        c = pair_ch.get((a, b))
        return (c.most_common(1)[0][1] / tot) if c else 0.0

    def pick(t: str, thr: float) -> list[str]:
        out = []
        for c in cand[t]:                      # 이미 점수 내림차순이다
            if share(t, c["tag"]) <= thr:
                out.append(c["tag"])
            if len(out) >= args.top:
                break
        return out

    gold = {c["tag"]: c for c in json.loads(GOLD.read_text(encoding="utf-8"))["cases"]}
    print()
    print(f"{'max-share':>10}{'바뀐 태그':>10}{'제거 간선':>10}{'골드 정밀도':>12}{'골드 손실':>10}")
    for thr in (0.30, 0.40, 0.50, 0.60, 0.70, 1.01):
        changed = removed = 0
        for t, cs in cand.items():
            cur = doc["companions"].get(t, [])
            new = pick(t, thr)
            if new != cur:
                changed += 1
            removed += sum(1 for c in cur if share(t, c) > thr)
        g_ok = g_tot = 0
        loss = []
        for t, spec in gold.items():
            if t not in cand:
                continue
            new = pick(t, thr)
            g_tot += len(new)
            g_ok += sum(1 for b in new if b in spec["good"])
            loss += [b for b in doc["companions"].get(t, [])
                     if b in spec["good"] and b not in new]
        print(f"{thr:>10.2f}{changed:>10}{removed:>10}{(g_ok/g_tot if g_tot else 0):>12.3f}"
              f"{len(loss):>10}  {loss[:3]}")

    if args.eval:
        print("\n--eval: 쓰지 않았습니다.")
        return 0

    changed = 0
    bias: dict[str, list[str]] = {}
    for t, cs in cand.items():
        cur = doc["companions"].get(t, [])
        new = pick(t, args.max_share)
        dropped = [c for c in cur if c not in new]
        if new != cur:
            changed += 1
        if dropped:
            bias[t] = dropped
        if new:
            doc["companions"][t] = new
        else:
            doc["companions"].pop(t, None)
    doc["character_bias_dropped"] = {k: v for k, v in sorted(bias.items())}
    doc.setdefault("note", []).append(
        f"캐릭터 집중도 {args.max_share} 초과 간선을 걷었다 — 한 캐릭터가 동반 게시물의 "
        f"그 비율을 넘게 차지하면 태그 관계가 아니라 그 캐릭터의 디자인이다. "
        f"무엇을 걷었는지는 character_bias_dropped 에 있다.")
    CO.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"\n바뀐 태그 {changed} / 걷어낸 간선 {sum(len(v) for v in bias.values())}")
    print(f"저장: {CO}  ({CO.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
