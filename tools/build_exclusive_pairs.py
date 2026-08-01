# -*- coding: utf-8 -*-
"""배타 태그쌍 사전 — `data/tag_exclusive_pairs.json`.

## 무엇을 고치려는 것인가

`muscular`(근육질 몸)의 "비슷한 것" 에 `loli` 와 `child` 가 나왔다(사용자 실측 2026-07-30).
`interactive_tags.json` 이 체형 축 태그들을 서로 `siblings` 로 묶어 놓았고, 랭커는
"같은 subgroup + 같은 axis" 를 유사도 근거로 쓰므로 정상 경로로 통과한다. 즉 사전과
코드 모두 자기 규칙대로 동작하는데 결과가 틀렸다 — **'같은 종류'와 '비슷한 것'을 같은
것으로 취급한 것이 원인**이다. 체형은 하나를 고르면 다른 것과 공존하지 않는 축이다.

## 무엇을 근거로 배타를 판정하나

추측이 아니라 **실제 게시물 동반율**이다. `data/quick_search/` 의 52개 파티션(등급 4 ×
인원 13)이 태그 동반 관계를 담은 CSR 이다. 두 태그가 같은 게시물에 함께 달리는 비율이
0 에 가까우면, 사람들이 그 둘을 함께 쓰지 않는다는 뜻이고 "비슷한 것" 으로 제시할
근거가 없다.

    lift(a, b) = P(a AND b) / (P(a) * P(b))

**jaccard 를 쓰면 안 된다.** 처음에 그렇게 했다가 검사 대상의 77%(128,774쌍)가 배타로
잡혔다 — jaccard 는 두 태그의 빈도가 크게 다르면 아무리 붙어 다녀도 작아진다
(`shirt` 116만 x `bow panties` 2.2만은 항상 함께 나와도 0.012 다). lift 는 우연히
겹칠 기대치로 나누므로 빈도 비대칭에 벌점을 주지 않는다.

실측 보정값(2026-07-30):

    muscular x abs             25.391   유사
    muscular x muscular male   38.094   유사
    muscular x toned            4.467   유사
    muscular x curvy            1.016   중립
    muscular x loli             0.155   배타  <- 사용자가 본 그것
    loli     x child            0.002   배타
    pantyhose x thighhighs      0.726   중립 — '대안'이라 유지해야 한다

경계를 0.35 로 둔 근거가 이 표다. `pantyhose`/`thighhighs` 처럼 함께 입지는 않지만
**서로 갈아 끼우는 선택지**인 쌍은 살려야 하고(그게 고르는 화면에서 '비슷한 것'이다),
`muscular`/`loli` 처럼 우연 기대치의 1/6 밖에 안 겹치는 쌍은 근거가 없다.

## 왜 오프라인인가

코퍼스가 238MB 다. `/api/tag/lookup` 은 태그를 누를 때마다 불리므로 런타임에 올릴 수
없다. 여기서 계산해 작은 JSON 으로 떨어뜨리고, 랭커는 그 집합만 읽는다.

## 쓰는 법

    python tools/build_exclusive_pairs.py                 # 기본(사전의 siblings 전수)
    python tools/build_exclusive_pairs.py --max-lift 0.5
    python tools/build_exclusive_pairs.py --min-events 300 --dry-run
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from core.event_corpus_index import EventCorpusIndex, normalize_tag
from core.kr_tag_loader import load_kr_tag_records

OUT = Path("data/tag_exclusive_pairs.json")
DATA_ROOTS = [Path("NAIA-Portable/user-data/data"), Path("data")]


def main() -> int:
    ap = argparse.ArgumentParser(description="배타 태그쌍 사전 생성")
    ap.add_argument("--max-lift", type=float, default=0.35,
                    help="우연 기대치 대비 이 배수 이하면 배타로 본다 (기본 0.35)")
    ap.add_argument("--min-events", type=int, default=200,
                    help="두 태그 각각 이만큼은 등장해야 판정한다 — 표본이 얇으면 0 이 우연이다")
    ap.add_argument("--min-freq", type=int, default=500,
                    help="이 빈도 미만 태그는 건너뛴다 (기본 500)")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 통계만")
    args = ap.parse_args()

    raw = load_kr_tag_records().raw
    idx = EventCorpusIndex([p for p in DATA_ROOTS if p.exists()])
    idx._ensure_metadata()
    if not idx.tag_to_id:
        print("!! 이벤트 코퍼스를 읽지 못했습니다 (data/quick_search 확인)")
        return 2
    tag_to_id = idx.tag_to_id
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)   # noqa: E731

    # 검사 대상 — 사전이 `siblings` 로 묶은 쌍 전부. 그것이 "비슷한 것" 의 후보이고,
    # 지금 문제가 되는 경로다. word_match/children 은 다른 필터가 이미 본다.
    pairs: set[tuple[str, str]] = set()
    for tag, info in raw.items():
        if F(tag) < args.min_freq:
            continue
        rel = info.get("relations") or {}
        sibs = rel.get("siblings") or []
        if isinstance(sibs, str):
            sibs = [sibs]
        a = normalize_tag(tag)
        if len(a) < 2:                 # 이름이 빈/한 글자 레코드가 섞여 있다(실측)
            continue
        for s in sibs:
            b = normalize_tag(s)
            if not b or b == a or len(b) < 2 or F(b) < args.min_freq:
                continue
            pairs.add((a, b) if a < b else (b, a))
    print(f"검사 대상 {len(pairs)}쌍 (freq>={args.min_freq} 인 siblings 쌍)")

    # 태그 -> 등장 이벤트 집합. 파티션을 한 번만 열고 필요한 태그만 모은다.
    want = {t for pair in pairs for t in pair}
    posting: dict[str, set[int]] = {t: set() for t in want}
    total_events = 0
    names = sorted(p.stem for p in idx.root.glob("*.tgp")) if idx.root else []
    for pi, name in enumerate(names, 1):
        try:
            store = idx.store(name)
        except Exception as exc:
            print(f"  !! {name}: {exc}")
            continue
        # 이벤트 id 는 파티션마다 0 부터라 파티션 번호로 오프셋을 준다 — 안 그러면
        # 다른 파티션의 서로 다른 게시물이 같은 id 로 합쳐진다.
        total_events += idx.csr_arrays(store)[2]
        base = pi * 10_000_000
        for t in want:
            tid = tag_to_id.get(t)
            if tid is None:
                continue
            ev = idx.postings(store, tid)
            if ev is None or not len(ev):
                continue
            posting[t].update(base + int(x) for x in np.asarray(ev))
        print(f"  [{pi}/{len(names)}] {name}", flush=True)

    excl, thin, kept = [], 0, 0
    for a, b in sorted(pairs):
        sa, sb = posting.get(a) or set(), posting.get(b) or set()
        if len(sa) < args.min_events or len(sb) < args.min_events:
            thin += 1
            continue
        inter = len(sa & sb)
        # lift = 실제 동반 확률 / 서로 무관할 때의 기대 확률.
        expected = (len(sa) / total_events) * (len(sb) / total_events)
        lift = ((inter / total_events) / expected) if expected else 0.0
        if lift <= args.max_lift:
            excl.append([a, b, round(lift, 4), inter])
        else:
            kept += 1

    print(f"\n배타 {len(excl)}쌍 / 유지 {kept}쌍 / 표본부족 {thin}쌍")
    for a, b, j, inter in excl[:12]:
        print(f"  {a:<24} x {b:<24} lift={j:.4f} 동반={inter}")
    if args.dry_run:
        print("\n--dry-run: 쓰지 않았습니다.")
        return 0

    OUT.write_text(json.dumps({
        "note": [
            "배타 태그쌍. tools/build_exclusive_pairs.py 가 만든다.",
            "근거는 실제 게시물 동반 lift(우연 기대치 대비) — 추측이 아니다.",
            "core/tag_relation_ranker.py 가 '비슷한 것' 후보에서 이 쌍을 뺀다.",
            "형식: pairs = ['a\\tb', ...] (정렬된 두 태그를 탭으로 이었다)",
        ],
        "maxLift": args.max_lift,
        "minEvents": args.min_events,
        "minFreq": args.min_freq,
        "count": len(excl),
        "pairs": [f"{a}\t{b}" for a, b, _j, _i in excl],
        "detail": excl,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
