# -*- coding: utf-8 -*-
"""태그별 **대표 이벤트 앵커**를 이벤트 코퍼스에서 뽑는다.

## 무엇을 위한 것인가

지금 성인 축 벤치는 와일드카드 한 줄이다.

    2.5::__*th_nsfw/nsfw_hand__ ::, hand, 0.5::close-up, standing ::, rating:explicit

`hand` 와 `standing` 이 손으로 박혀 있어 축 전체가 같은 보조 태그를 쓴다. 목표 형태는

    <person>, 2.5::<tag> ::, <subtag1>, 0.5::close-up, <subtag2> ::, rating:explicit

이고, `<person>` · `<subtag1>` · `<subtag2>` 를 **태그마다** 다르게 채우려면 그 태그가
실제로 어떤 맥락에서 쓰이는지를 알아야 한다. 이벤트 코퍼스가 그 답을 갖고 있다 —
`data/quick_search/` 의 52개 파티션(등급 4 × 인원 13)이 태그 동반 관계를 담은 CSR 이다.

## 어떻게 뽑는가

  1. `<person>` — 그 태그가 가장 많이 나타나는 파티션의 인원 범주. 파티션 이름이
     `e_1girl_1boy` 처럼 등급+인원이라 따로 추론할 필요가 없다.
  2. `<subtag1>` — 그 파티션에서 함께 나온 `Person_Body` 태그 1위(부위·체형 앵커).
  3. `<subtag2>` — 같은 곳의 `Expression_Action` / `Composition_Meta` 태그 1위(자세·구도).

순위는 **동반 빈도가 아니라 lift** 로 낸다.

    lift(c) = P(c | 대상) / P(c)   =  (동반수/대상수) / (파티션 전체 c 수/전체 이벤트 수)

처음엔 동반 빈도만 썼더니 `subtag1` 이 거의 전부 `breasts`, `subtag2` 가 `blush` 로
나왔다(실측). 그 둘은 explicit 이벤트 어디에나 있어서 무엇을 넣어도 1위다 — 대상 태그의
**특징**이 아니라 코퍼스의 배경값이다. lift 는 배경을 나눠 없애므로 `buttjob` 에서는
`ass`, `asymmetrical docking` 에서는 `breast press` 처럼 그 태그다운 것이 올라온다.

표본이 적어 lift 만 큰 잡음을 막으려고 **동반수 하한**(대상 등장수의 일정 비율)을 함께 건다.

## 쓰는 법

    python tools/nsfw_event_anchor.py                    # 남은 것 전부(_todo 기준)
    python tools/nsfw_event_anchor.py nsfw_hand          # 한 축만
    python tools/nsfw_event_anchor.py --all              # 도감 전체
    python tools/nsfw_event_anchor.py --min-events 200   # 표본이 적은 태그는 버린다

결과는 두 갈래로 쓴다.

  · `wildcards/nsfw/_event_anchor.json`        슬롯별 후보 3개 + 이벤트 수 + lift 값
  · `wildcards/nsfw/_event_anchor_prompts.txt` 바로 쓸 수 있는 프롬프트(주석·빈 줄 없음)
  · `wildcards/nsfw/_event_anchor_<축>.txt`    축별 묶음

**벤치가 이 파일을 읽지는 않는다.** `thumb_bench.py` 는 여전히 `_bench.json` 의 고정
템플릿으로만 프롬프트를 만든다. 이 도구의 산출물은 **사용자가 와일드카드로 직접 돌리는
용도**다(Codex 리뷰 2026-07-30 지적 — 전에는 이 자리에 "벤치가 이걸 읽어 조립한다"고
적어놨는데 그런 배선은 없다).
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from core.event_corpus_index import EventCorpusIndex, normalize_tag
from core.kr_tag_loader import load_kr_tag_records

NSFW = Path("wildcards/nsfw")
TODO = Path("wildcards/thumb/_todo")
OUT = NSFW / "_event_anchor.json"
DATA_ROOTS = [Path("NAIA-Portable/user-data/data"), Path("data")]

# 인원 범주 -> 프롬프트에 넣을 인물 토큰. 파티션 이름이 곧 인원이라 여기서 문자열만 만든다.
PERSON_PROMPT = {
    "1girl_solo": "1girl, solo",
    "1boy_solo": "1boy, solo",
    "1girl": "1girl",
    "1boy": "1boy",
    "1girl_1boy": "1girl, 1boy",
    "2girls": "2girls",
    "2boys": "2boys",
    "1girl_multiple_boys": "1girl, multiple boys",
    "1boy_multiple_girls": "1boy, multiple girls",
    "multiple_girls": "multiple girls",
    "multiple_boys": "multiple boys",
    "multiple_girls_multiple_boys": "multiple girls, multiple boys",
    "other": "1girl",
}
RATING_PROMPT = {"g": "rating:general", "s": "rating:sensitive",
                 "q": "rating:questionable", "e": "rating:explicit"}

# 후보에서 뺄 것. 인원·등급은 슬롯이 따로 있고, 메타는 그림에 안 보인다.
SKIP_TAGS = {
    "1girl", "1boy", "2girls", "2boys", "solo", "multiple girls", "multiple boys",
    "multiple views", "male focus", "female focus", "solo focus",
    "highres", "absurdres", "commentary", "commentary request", "translated",
    "artist name", "signature", "watermark", "censored", "uncensored",
    "nsfw", "safe", "questionable", "explicit", "general", "sensitive",
}
# 슬롯별로 받을 그룹. `<subtag1>` 은 부위·체형 앵커, `<subtag2>` 는 자세·구도다.
GROUP_SUB1 = {"Person_Body"}
GROUP_SUB2 = {"Expression_Action", "Composition_Meta"}

# **연령·금기 태그는 후보에서 하드 차단한다.** 첫 실행에서 `bar censor` 의 subtag1 이
# `loli` 로 나왔다(실측). `thumb_bench.py` 의 가드가 요청 직전에 막긴 하지만, 앵커 파일이
# 그것을 **제안하는 것 자체**가 사고다 — 사람이 그 줄을 보고 손으로 옮겨 쓸 수 있다.
# 코퍼스는 실제 게시물 통계라 이런 것이 자연히 올라온다. 여기서 끊는다.
# 연령·금기는 `tools/thumb_age_guard.py` 가 단일 출처다. 여기에 목록을 또 적었더니
# `teenage` 가 빠져 있었다 — `teen\b` 는 "teenage" 를 안 잡고, 태그 DB 도 그것을
# `Person_Body` 로 분류해 그룹 검사도 통과했다(Codex 리뷰 2026-07-30 실측).
from tools.thumb_age_guard import danger_age_hits  # noqa: E402

# 연령 외 금기(구로·료나 등)는 여기서 본다 — 연령 게이트와 성격이 다르다.
TABOO_RE = __import__("re").compile(
    r"\b(rape|guro|ryona|scat|feces|vore|torture|snuff|bestial|incest|cest"
    r"|molest|necro|amputee|mutilat)", __import__("re").I)
DANGER_GROUPS = {"Danger"}

# 남성-남성 파티션. `--no-mm` 이면 인원 선택에서 뺀다.
# 코퍼스는 "가장 많이 나온 곳" 을 고르므로 `cum on pectorals` · `bulge to ass` 처럼
# 남녀로도 성립하는 태그가 통계상 2boys 로 앵커됐다(사용자가 그 결과물을 걷어냈다).
# 정의상 남성 둘이어야 하는 것(`pectoral docking` 류)은 대체 파티션이 없으므로
# 표본 하한에 걸려 자연히 빠진다 — 억지로 다른 인원을 붙이지 않는다.
MM_PERSONS = {"2boys", "multiple_boys"}
# **표기 변형을 다 적어야 한다.** `otokonoko` 만 넣었더니 코퍼스 표기인 `otoko no ko`
# 가 `futa on male` 의 subtag2 로 새어 들어갔다(실측). 집합 비교는 철자가 정확해야 한다.
MM_TAGS = {"yaoi", "bara", "male focus", "josou seme",
           "otokonoko", "otoko no ko", "trap", "crossdressing"}

# 그림에 안 나오는 메타. `Composition_Meta` 그룹에는 화면 UI·도표·별자리처럼 구도가
# 아닌 것이 섞여 있어, 표본이 얇은 태그에서 lift 1위로 올라온다(실측: `pectoral docking`
# -> `loading screen`, `futa on male` -> `holding game controller`,
#  `intravaginal futanari` -> `capricorn (zodiac)`). 프롬프트에 넣을 것이 아니다.
NOISE_RE = __import__("re").compile(
    r"loading screen|relationship graph|\bgraph\b|\bchart\b|zodiac|\bmeme\b"
    r"|game controller|\blogo\b|subtitled|translation request|\bborder\b"
    r"|character name|copyright name|dated|reference sheet|\bguide\b|\bruler\b")


def load_targets(args, raw) -> dict[str, list[str]]:
    if args.axes:
        names = args.axes
    elif args.all:
        names = sorted(p.stem for p in NSFW.glob("nsfw_*.txt") if p.stem != "nsfw_heavy")
    else:
        names = sorted(p.stem for p in TODO.glob("nsfw_*.txt"))
    out = {}
    for n in names:
        src = (TODO / f"{n}.txt") if not args.all and not args.axes else (NSFW / f"{n}.txt")
        if args.axes and not src.exists():
            src = TODO / f"{n}.txt"
        if not src.exists():
            print(f"  (건너뜀: {n} 목록 없음)")
            continue
        out[n] = [l.strip() for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="태그별 대표 이벤트 앵커 추출")
    ap.add_argument("axes", nargs="*", help="축 이름 (없으면 _todo 의 남은 것 전부)")
    ap.add_argument("--all", action="store_true", help="도감 전체")
    ap.add_argument("--min-events", type=int, default=50,
                    help="이만큼도 안 나오는 태그는 앵커를 만들지 않는다 (기본 50)")
    ap.add_argument("--top", type=int, default=3, help="슬롯별 후보 수 (기본 3)")
    ap.add_argument("--no-mm", action="store_true",
                    help="남성-남성 파티션(2boys/multiple_boys)을 인원 후보에서 뺀다")
    ap.add_argument("--support", type=float, default=0.20,
                    help="동반수 하한 = 대상 등장수 x 이 값. lift 잡음 방지 (기본 0.10)")
    args = ap.parse_args()

    raw = load_kr_tag_records().raw
    G = lambda t: str((raw.get(t) or {}).get("group", "") or "")   # noqa: E731

    idx = EventCorpusIndex([p for p in DATA_ROOTS if p.exists()])
    idx._ensure_metadata()
    if not idx.tag_to_id:
        print("!! 이벤트 코퍼스를 읽지 못했습니다 (data/quick_search 확인)")
        return 2
    tag_to_id, id_to_tag = idx.tag_to_id, idx.id_to_tag
    num_tags = idx.num_tags

    targets = load_targets(args, raw)
    want = {t for v in targets.values() for t in v}
    print(f"대상 {len(want)}개 / {len(targets)}축 · 코퍼스 어휘 {len(tag_to_id)}개")

    # 태그 -> (최다 이벤트 수, 파티션). 파티션을 한 번만 열도록 밖에서 순회한다.
    best: dict[str, tuple[int, str]] = {}
    cooc: dict[str, np.ndarray] = {}
    base: dict[str, tuple[np.ndarray, int]] = {}   # 파티션 배경 분포 (lift 분모)
    root = idx.root
    names = sorted(p.stem for p in root.glob("*.tgp")) if root else []
    for pi, name in enumerate(names, 1):
        try:
            store = idx.store(name)
        except Exception as exc:
            print(f"  !! {name}: {exc}")
            continue
        indptr, indices, n_events = idx.csr_arrays(store)
        # 배경 분포는 파티션마다 한 번만 센다(lift 의 분모).
        base[name] = (np.bincount(indices, minlength=num_tags)[:num_tags], max(n_events, 1))
        if args.no_mm and name.split("_", 1)[1] in MM_PERSONS:
            continue
        for tag in want:
            tid = tag_to_id.get(normalize_tag(tag))
            if tid is None:
                continue
            ev = idx.postings(store, tid)
            if ev is None or len(ev) < args.min_events:
                continue
            if tag in best and best[tag][0] >= len(ev):
                continue
            # 이 태그를 포함한 이벤트들의 태그를 전부 센다.
            starts = indptr[ev]
            lens = (indptr[np.asarray(ev) + 1] - starts).astype(np.int64)
            total = int(lens.sum())
            offsets = np.repeat(starts - np.concatenate(([0], np.cumsum(lens)[:-1])), lens)
            counts = np.bincount(indices[offsets + np.arange(total)], minlength=num_tags)
            best[tag] = (len(ev), name)
            cooc[tag] = counts[:num_tags]
        print(f"  [{pi}/{len(names)}] {name}", flush=True)

    result, thin, blocked = {}, [], set()
    for tag in sorted(want):
        if tag not in best:
            thin.append(tag)
            continue
        n_ev, part = best[tag]
        rating, person = part.split("_", 1)
        counts = cooc[tag]
        bg, bg_n = base[part]
        # lift = 대상 안에서의 비율 / 파티션 전체에서의 비율.
        # 동반수 하한을 먼저 걸어 표본 부족으로 lift 만 큰 잡음을 버린다.
        floor = max(3, int(n_ev * args.support))
        ok = counts >= floor
        lift = np.zeros(num_tags, dtype=np.float64)
        denom = np.maximum(bg.astype(np.float64) / bg_n, 1e-9)
        lift[ok] = (counts[ok] / n_ev) / denom[ok]
        # 2단계 선택. lift 상위를 먼저 채우고, 남으면 동반빈도 1위로 메운다.
        #   lift 만  -> 사례가 특징적이지 않은 축에서 슬롯이 통째로 빈다(56/41 실측).
        #   빈도만    -> 전부 breasts / blush 가 된다(첫 실행 실측).
        # 둘 다 필요하다. 원래 손으로 쓰던 프롬프트도 일반적인 hand 를 넣고 있었으므로
        # 빈 슬롯보다는 일반 태그라도 채우는 편이 그때 동작과 같다.
        s1, s2 = [], []
        for tier in ("lift", "count"):
            order = np.argsort(-lift if tier == "lift" else -counts)
            for tid in order:
                if tier == "lift" and lift[tid] < 1.2:
                    break
                if tier == "count" and counts[tid] < floor:
                    break
                cand = id_to_tag.get(int(tid))
                if not cand or cand == normalize_tag(tag) or cand in SKIP_TAGS:
                    continue
                g = G(cand)
                # 연령·금기는 세 겹으로 막는다: 이름 집합 · 이름 규칙 · 태그 DB 의 Danger 그룹.
                if NOISE_RE.search(cand):
                    continue
                if args.no_mm and cand in MM_TAGS:
                    continue
                if danger_age_hits(cand) or TABOO_RE.search(cand) or g in DANGER_GROUPS:
                    blocked.add(cand)
                    continue
                row = [cand, int(counts[tid]), round(float(lift[tid]), 1), tier]
                if g in GROUP_SUB1 and not any(r[0] == cand for r in s1) and len(s1) < args.top:
                    s1.append(row)
                elif g in GROUP_SUB2 and not any(r[0] == cand for r in s2) and len(s2) < args.top:
                    s2.append(row)
                if len(s1) >= args.top and len(s2) >= args.top:
                    break
            if s1 and s2:
                break
        result[tag] = {
            "person": person, "rating": rating,
            "personPrompt": PERSON_PROMPT.get(person, "1girl"),
            "ratingPrompt": RATING_PROMPT.get(rating, "rating:explicit"),
            "events": n_ev,
            "subtag1": s1[0][0] if s1 else None,
            "subtag2": s2[0][0] if s2 else None,
            "sub1Candidates": s1, "sub2Candidates": s2,
        }

    # 바로 붙여 쓸 수 있는 프롬프트 줄도 같이 낸다 — 사람이 JSON 을 조립하지 않게.
    for tag, a in result.items():
        parts = [a["personPrompt"], f'2.5::{tag} ::']
        if a["subtag1"]:
            parts.append(a["subtag1"])
        inner = ["close-up"] + ([a["subtag2"]] if a["subtag2"] else [])
        parts.append("0.5::" + ", ".join(inner) + " ::")
        parts.append(a["ratingPrompt"])
        a["prompt"] = ", ".join(parts)

    by_axis = {ax: {t: result[t] for t in v if t in result} for ax, v in targets.items()}
    # **와일드카드 파일이므로 주석도 빈 줄도 없다.** 앱이 한 줄을 한 값으로 읽으므로
    # `# --- nsfw_act ---` 같은 머리글이 그대로 프롬프트로 뽑힌다(사용자 지적 2026-07-30).
    # 축별 묶음이 필요하면 `_event_anchor_<축>.txt` 를 쓴다.
    prompt_lines = [result[t]["prompt"] for ax in sorted(by_axis) for t in sorted(by_axis[ax])]
    (NSFW / "_event_anchor_prompts.txt").write_text(
        "\n".join(prompt_lines) + "\n", encoding="utf-8")
    for ax, tags in by_axis.items():
        f = NSFW / f"_event_anchor_{ax}.txt"
        if not tags:
            f.unlink(missing_ok=True)
            continue
        f.write_text("\n".join(result[t]["prompt"] for t in sorted(tags)) + "\n",
                     encoding="utf-8")
    OUT.write_text(json.dumps({
        "note": [
            "태그별 대표 이벤트 앵커. tools/nsfw_event_anchor.py 가 만든다.",
            "person/rating 은 그 태그가 가장 많이 나타난 파티션에서 왔다.",
            "subtag1=Person_Body 1위(부위 앵커), subtag2=Expression_Action/Composition_Meta 1위(자세·구도).",
            "형태: <personPrompt>, 2.5::<태그> ::, <subtag1>, 0.5::close-up, <subtag2> ::, <ratingPrompt>",
        ],
        "minEvents": args.min_events,
        "anchors": result,
        "byAxis": {k: sorted(v) for k, v in by_axis.items()},
        "thin": thin,
        "blockedCandidates": sorted(blocked),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n앵커 {len(result)}개 -> {OUT}")
    if blocked:
        print(f"연령·금기로 차단한 후보 {len(blocked)}개: {sorted(blocked)[:14]}")
    if thin:
        print(f"표본 부족({args.min_events}건 미만) {len(thin)}개: {thin[:12]}")
    from collections import Counter
    print("인원 분포:", Counter(v["person"] for v in result.values()).most_common())
    print("등급 분포:", Counter(v["rating"] for v in result.values()).most_common())
    return 0


if __name__ == "__main__":
    sys.exit(main())
