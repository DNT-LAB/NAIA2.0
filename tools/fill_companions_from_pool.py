# -*- coding: utf-8 -*-
"""후보가 4개 미만인 태그를 게시물 풀에서 채운다.

## 무엇을 고치려는 것인가

`tools/build_tag_cooccurrence.py` 는 이벤트 코퍼스(`data/quick_search/`, 449만 이벤트)를
쓴다. 그런데 그 코퍼스의 어휘는 **16,625개로 선별돼 있다** — 상위 N 개가 아니다.
실측: `collared shirt`(27만) · `black headwear`(10.7만) · `two-tone hair` 같은 색 수식어·
우산·시점 태그가 통째로 없다. 그래서

  · 축 태그 215개는 후보를 **하나도** 얻을 수 없고(어휘 밖),
  · 9,995개 대상 중 280개는 후보가 1~3개로 부분만 찼다.

`data/tag_pool_*.parquet`(tools/merge_tag_shards.py 가 만든다)은 Danbooru 게시물 원본이라
`general` 열에 전체 어휘가 있다. 그 풀에서 부족분을 채운다.

## 정책은 새로 쓰지 않는다

점수식·게이트·제외 필터는 `tools/build_tag_cooccurrence` 에서 **임포트해 쓴다.**
여기에 다시 적으면 두 출처의 판정이 갈라진다 — 이 리포의 상습 결함이 그것이다.

다만 **표본 하한은 풀 크기에 맞춰 줄인다.** 이벤트 코퍼스가 449만인데 이 풀은 140만이라,
같은 절대 하한(동반 30건)을 쓰면 코퍼스에서 통과했던 쌍도 여기서는 떨어진다.
동반 30 -> 12, 후보 빈도 800 -> 400 으로 줄이고, 줄인 만큼 lift 를 2.0 -> 2.5 로 올려
소표본 우연을 막았다(아래 인자 정의에 네 조합의 실측 비교가 있다).

그리고 **이 풀에만 있는 함정이 하나 더 있다.** 샤드는 시간 순 슬라이스라 120~139 는
2024-07-30 ~ 2025-05-20 약 10개월이다. 그 시기 유행 태그는 풀 안에서만 흔해서 무엇에든
lift 가 뜬다(`:o -> hasu no sora school uniform`). 전체 기간 빈도와 대조해 걸러낸다
(`--max-era-ratio`, 실측 193~374건 제거).

## 출처를 섞지 않는다

채운 것은 `pool_filled` 에 따로 기록한다. 나중에 "이 후보는 어디서 왔나" 를 다시
조사하지 않으려면 섞은 시점에 적어야 한다.

## 쓰는 법

    python tools/fill_companions_from_pool.py --dry-run
    python tools/fill_companions_from_pool.py
    python tools/fill_companions_from_pool.py --include-empty   # 후보 0개인 것도(축 어휘 밖 215개)
"""
import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from core.kr_tag_loader import load_kr_tag_records
from core.tag_relation_ranker import _is_negation_pair, is_exclusive_pair
from tools.build_tag_cooccurrence import (BAD_GROUPS, BAD_SUBGROUPS, STOP,
                                          _adult_vocab, _relation_neighbors, axis_tags,
                                          same_family)
from tools.thumb_age_guard import danger_age_hits

CO = Path("data/tag_cooccurrence.json")
POOL = Path("data/tag_pool_120_139.parquet")


def main() -> int:
    ap = argparse.ArgumentParser(description="게시물 풀로 동반 후보 부족분 채우기")
    ap.add_argument("--pool", default=str(POOL))
    ap.add_argument("--top", type=int, default=4, help="태그당 목표 후보 수")
    # 기본값은 실측 비교로 골랐다(대상 280개, 시대 편향 가드 켜고):
    #   min-pair 10 / lift 2.0  -> 209태그 356후보  (`alpaca -> shoes` 같은 약한 것 다수)
    #   min-pair 12 / lift 2.5  -> 169태그 263후보  <- 채택
    #   min-pair 25 / lift 2.0  ->  65태그  89후보
    #   min-pair 25 / lift 4.0  ->  34태그  46후보  (품질은 최고지만 280개를 못 채운다)
    # 이 풀은 이벤트 코퍼스의 1/3 이라 표본 하한이 곧 노이즈 조절 손잡이다. 낮추면
    # 커버리지가 오르는 대신 소표본 우연이 들어온다. lift 를 올려 그것을 보완했다.
    ap.add_argument("--min-pair", type=int, default=12, help="동반 게시물 하한")
    ap.add_argument("--support-ratio", type=float, default=0.01)
    ap.add_argument("--min-cand-freq", type=int, default=400, help="후보 자체 등장 하한")
    ap.add_argument("--strict-lift", type=float, default=2.5)
    ap.add_argument("--max-cand-prob", type=float, default=0.30)
    ap.add_argument("--implication-conf", type=float, default=0.95,
                    help="P(후보|대상) 또는 P(대상|후보) 가 이 이상이면 함의로 보고 제외")
    # **시대 편향 가드.** 샤드는 시간 순 슬라이스다 — 120~139 는 2024-07-30 ~ 2025-05-20
    # 약 10개월이다. 그 시기에 유행한 작품·의상 태그는 이 풀 안에서만 흔해서 무엇에든
    # lift 가 뜬다(실측: `:o -> hasu no sora school uniform`, 2024~25 유행 작품 교복).
    # 태그 DB 의 freq 는 Danbooru 전체 기간이므로, 풀 안 등장률이 전체 기간 등장률보다
    # 이 배수 넘게 높으면 그 시기 유행으로 보고 버린다.
    ap.add_argument("--max-era-ratio", type=float, default=3.0,
                    help="풀 등장률 / 전체기간 등장률 상한. 넘으면 그 시기 유행으로 버린다")
    ap.add_argument("--danbooru-total", type=int, default=10_000_000,
                    help="전체기간 게시물 수 추정(태그 DB freq 의 분모). 샤드 id 최대가 약 999만")
    ap.add_argument("--include-empty", action="store_true",
                    help="후보가 0개인 태그도 대상에 넣는다(축 태그 전체를 훑는다)")
    # **이벤트 코퍼스가 국소적으로 오염돼 있다.** 원본 게시물과 대조하면 2.1%(189개)에서
    # 코퍼스가 말하는 동반이 실제로는 거의 없다 — `hooded coat + cow ears` 는 코퍼스 3,333회인데
    # 게시물에서는 **0회**다. `racing suit` 의 후보 넷이 127/127/126/126 으로 거의 같은 수인 것도
    # 같은 지문이다(무관한 태그가 한 이벤트에 통째로 묶여 있다).
    # 빈도로는 안 갈린다 — 층화 표본 253개에서 빈도대별 미지지율이 0~7.5% 로 고르다.
    # 그래서 **대조로 특정한 목록만** 통째로 버리고 원본 게시물에서 다시 뽑는다.
    ap.add_argument("--replace-tags", default="",
                    help="한 줄 한 태그 파일. 그 태그들은 기존 후보를 버리고 풀에서 새로 뽑는다")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pool = Path(args.pool)
    if not pool.exists():
        raise SystemExit(f"{pool} 가 없다. tools/merge_tag_shards.py 120 139 를 먼저 돌려라.")
    doc = json.loads(CO.read_text(encoding="utf-8"))
    companions: dict[str, list[str]] = doc.get("companions") or {}

    raw = load_kr_tag_records().raw
    # 대상: 후보가 목표보다 적은 태그. `--include-empty` 면 후보가 아예 없는 축 태그까지.
    replace: set[str] = set()
    if args.replace_tags:
        replace = {l.strip().lower() for l in
                   Path(args.replace_tags).read_text(encoding="utf-8").splitlines() if l.strip()}
        print(f"교체 대상 {len(replace)}개 (기존 후보를 버리고 다시 뽑는다)")
    targets = {t for t, v in companions.items() if len(v) < args.top}
    if args.include_empty:
        targets |= {t for t in axis_tags() if t not in companions}
    targets = {t.strip().lower() for t in targets if t.strip()} | replace
    print(f"대상 {len(targets)}개 (후보 {args.top}개 미만"
          f"{' + 후보 없음' if args.include_empty else ''})")

    # ── 한 번만 훑는다: 전역 빈도와 대상별 동반을 동시에 센다 ──────────────────
    total = 0
    gfreq: Counter[str] = Counter()
    co: dict[str, Counter[str]] = defaultdict(Counter)
    pf = pq.ParquetFile(pool)
    for bi, batch in enumerate(pf.iter_batches(batch_size=50_000, columns=["general"]), 1):
        for g in batch.column(0).to_pylist():
            if not g:
                continue
            tags = [x.strip().lower() for x in str(g).split(",")]
            tags = [x for x in tags if x]
            if not tags:
                continue
            total += 1
            uniq = set(tags)
            gfreq.update(uniq)
            hit = uniq & targets
            if hit:
                for a in hit:
                    co[a].update(uniq)
        print(f"  배치 {bi}: 누계 {total:,}게시물 / 어휘 {len(gfreq):,}", flush=True)

    print(f"\n풀 {total:,}게시물 / 어휘 {len(gfreq):,}개 / 동반을 센 대상 {len(co)}개")

    # ── 필터 재료 (빌더와 같은 것) ────────────────────────────────────────────
    neighbors = _relation_neighbors(raw)
    adult = _adult_vocab()

    def bad_class(t: str) -> bool:
        m = raw.get(t) or {}
        return (str(m.get("group") or "") in BAD_GROUPS
                or str(m.get("subgroup") or "").lower() in BAD_SUBGROUPS)

    filled: dict[str, list[str]] = {}
    drop = Counter()
    for a in sorted(targets):
        have = [] if a in replace else [x for x in companions.get(a, [])]
        have_lower = {x.strip().lower() for x in have}
        need = args.top - len(have)
        if need <= 0:
            continue
        cnts = co.get(a)
        if not cnts:
            drop["대상이 풀에 없음"] += 1
            continue
        fa = gfreq.get(a, 0)
        if fa <= 0:
            drop["대상이 풀에 없음"] += 1
            continue
        floor = max(args.min_pair, args.support_ratio * fa)
        scored = []
        for b, c in cnts.items():
            if b == a:
                continue
            if c < floor:
                drop["표본 부족"] += 1
                continue
            fb = gfreq.get(b, 0)
            if fb < args.min_cand_freq:
                drop["후보가 희귀"] += 1
                continue
            pb = fb / total
            if pb > args.max_cand_prob:
                drop["너무 흔함"] += 1
                continue
            lift = (c / total) / ((fa / total) * pb) if pb > 0 else 0.0
            if lift < args.strict_lift:
                drop["lift 미달"] += 1
                continue
            # **함의는 동반이 아니다.** 후보가 대상의 상위/하위 개념이면 UI 의 다른 줄이 담당한다.
            # 관계 사전에 그 쌍이 없어도 **동반 통계 자체로 판정할 수 있다** — 조건부 확률의 비대칭이다:
            #   P(underwear | panties) = 1.000  <- panties 를 쓰면 반드시 underwear 다 (부모)
            #   P(hair ornament | hairclip) = 1.000  <- 역방향. hairclip 은 hair ornament 의 하나 (자식)
            # 실측(게시물 풀 140만, Codex 가 variant/parent/same 로 잡은 87쌍 대상):
            #   0.95 하한 -> 23쌍 적출, 골드 '나와야' 손실 0, 다른 유형 오탐 0
            #   0.90 으로 낮추면 `silent princess -> pointy ears`(0.923) 가 골드에서 잘린다
            # 골드 정답은 한참 아래다: beach->ocean 0.528 · cat ears->tail 0.555 · sweater->long sleeves 0.469
            if c / fa >= args.implication_conf or c / max(fb, 1) >= args.implication_conf:
                drop["함의(부모/자식)"] += 1
                continue
            # **태그 DB 에 없는 것은 내보내지 않는다.** 설명도 빈도도 없는 문자열이
            # 칩으로 나가면 사용자가 그것이 무엇인지 알 방법이 없다.
            if b not in raw:
                drop["태그 DB 에 없음"] += 1
                continue
            # 그 시기에만 흔한 태그를 걸러낸다(위 --max-era-ratio 주석 참조).
            all_time = int((raw.get(b) or {}).get("freq", 0) or 0)
            if all_time > 0:
                era = pb / (all_time / args.danbooru_total)
                if era > args.max_era_ratio:
                    drop["시대 편향"] += 1
                    continue
            if b in STOP:
                drop["STOP"] += 1
                continue
            if b in have_lower:
                drop["이미 있음"] += 1
                continue
            if danger_age_hits(b):
                drop["연령 어휘"] += 1
                continue
            if _is_negation_pair(a, b):
                drop["부정쌍"] += 1
                continue
            if is_exclusive_pair(a, b):
                drop["배타쌍"] += 1
                continue
            if b in neighbors.get(a, ()) or a in neighbors.get(b, ()):
                drop["관계 중복"] += 1
                continue
            if b in adult and a not in adult:
                drop["성인"] += 1
                continue
            if bad_class(b):
                drop["분류 제외"] += 1
                continue
            if same_family(raw, a, b):
                drop["같은 계열 변형"] += 1
                continue
            conf = c / fa
            scored.append((conf * min(math.log2(max(lift, 1.0)), 3.0), b))
        if not scored:
            continue
        scored.sort(reverse=True)
        add = [b for _s, b in scored[:need]]
        if add:
            filled[a] = add

    print("\n버린 후보:", dict(drop.most_common()))
    print(f"채운 태그 {len(filled)}개 / 추가된 후보 {sum(len(v) for v in filled.values())}개")
    ex = [t for t in filled if len(companions.get(t, [])) == 0][:6]
    print("\n예시 — 원래 비어 있던 것:")
    for t in ex:
        print(f"  {t:<24}-> {', '.join(filled[t])}")
    print("예시 — 부분만 차 있던 것:")
    for t in [t for t in filled if companions.get(t)][:8]:
        print(f"  {t:<24}{companions[t]}  + {filled[t]}")

    if args.dry_run:
        print("\n--dry-run: 쓰지 않았습니다.")
        return 0

    for a, add in filled.items():
        base = [] if a in replace else list(companions.get(a, []))
        companions[a] = base + add
    # 교체 대상인데 풀에서도 아무것도 못 뽑은 것은 **빈 목록으로 둔다.** 틀린 것을
    # 남겨두는 것보다 안 내보내는 것이 이 프로젝트의 정책이다.
    for a in replace:
        if a not in filled and a in companions:
            del companions[a]
    doc["companions"] = companions
    # 출처를 남긴다 — 섞은 시점에 적지 않으면 나중에 다시 조사하게 된다.
    doc["pool_filled"] = {a: add for a, add in sorted(filled.items())}
    doc.setdefault("note", []).append(
        f"부족분 {len(filled)}태그 {sum(len(v) for v in filled.values())}후보는 "
        f"{pool.name}({total:,}게시물)에서 채웠다 — tools/fill_companions_from_pool.py. "
        f"어느 후보가 그것인지는 pool_filled 에 있다.")
    CO.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"\n저장: {CO}  ({CO.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
