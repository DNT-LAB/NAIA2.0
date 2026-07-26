# -*- coding: utf-8 -*-
"""자세 슬롯 목록 생성 — 개별(1인) / 글로벌(다인원) / 제외.

    python tools/build_pose_slots.py

## 판정 근거의 우선순위

1. **태그 이름의 own / another's** — 결정적이다. 추론이 필요 없다.
   Danbooru 가 모호한 상위 태그를 이미 둘로 쪼개 놨다.
       hand in own hair        2,073   -> 개별
       hand in another's hair    745   -> 글로벌
   실측 10샤드에서 own 계열 156종 / another's 계열 244종이 잡혔고,
   98개 개념이 양쪽 짝을 모두 갖고 있다.

2. **이벤트 프리셋 파티션의 실측 solo 비율** (`data/interactive_preset_facts.json`)
   `{등급}_{인원구성}` 40개 파티션의 실제 post_count. 세면 되는 것을 추론하지 않는다.
       hug 3.1% / kiss 0.9% / clothes pull 61.4% / sitting 67.0%

3. **LLM 2인 합의** (Codex + 서브에이전트). 위 둘이 없을 때만.

## 모호한 우산 태그는 버린다

`hands in hair`(freq 4,321)는 **실제 데이터에 존재하지 않는다** — 최신 10샤드
65.6만 건에서 0회다. 설명도 "자신의 머리나 다른 사람의 머리"라 어느 쪽인지 모른다.
이런 우산 태그를 슬롯에 넣으면 초보자가 골라도 원하는 그림이 안 나온다.
own/another's 변형이 둘 다 있으면 우산은 제외하고 변형만 제공한다.

## 표시 이름

개별 슬롯에서는 모든 태그가 '자기 것'이므로 화면에는 `own` 을 지운 이름을 쓴다
(`hand on own hip` -> "손을 허리에"). 글로벌 슬롯에서만 "상대의" 를 붙인다.
어색한 영어를 사용자에게 보여줄 이유가 없다.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from core.kr_tag_loader import load_kr_tag_records
import core.interactive_browse_index as ib
from core.interactive_pose_evidence import (get_pose_evidence, parse_classification,
                                            slot_of)

OUT = Path("wildcards/thumb")
SCRATCH = Path("C:/Users/meno9/AppData/Local/Temp/claude/C--VNR-DEV-NAIA2-0"
               "/c793186c-0202-4d39-8740-f0ede25f24fb/scratchpad")
MIN_FREQ = 100
# 원본 parquet 직접 쿼리로 확정한 판정(tools/query_tag_cooccurrence.py).
# 프리셋 파티션에 없거나 표본이 부족했던 것만 담는다 — 가장 강한 근거라 맨 앞에 온다.
MEASURED_PATH = OUT / "_pose_measured.json"

RE_OWN = re.compile(r"\bown\b")
RE_OTH = re.compile(r"another's|other's")
# 성기·가슴·엉덩이 접촉 계열은 성인 축이 따로 담당한다.
RE_NSFW = re.compile(r"(penis|pussy|balls|testicl|nipple|anus|genital|cum\b|breast"
                     r"|\bass\b|butt|crotch|masturbat|fellatio|paizuri)")
# 데이터가 "변형을 쓰라"고 명시한 우산 태그.
RE_REDIRECT = re.compile(r"(참고하세요|중 하나를|를 사용|모호한 태그)")


def strip_own(tag: str) -> str:
    return re.sub(r"\bown\s+", "", tag).replace("  ", " ").strip()


def base_concept(tag: str) -> str:
    return re.sub(r"\b(own|another's|other's)\s*", "", tag).replace("  ", " ").strip()


def main() -> int:
    raw = load_kr_tag_records().raw
    idx = ib.InteractiveBrowseIndex(raw)
    ev = get_pose_evidence()
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)
    D = lambda t: str((raw.get(t) or {}).get("description") or "")

    # 자세 후보 풀: pose_action 슬롯 + own/another's 변형(그룹이 어디든)
    pool: set[str] = set()
    for s in idx.subgroups("pose_action"):
        for it in idx.tags_in("pose_action", s["id"], 0, 5000)["items"]:
            if it["count"] >= MIN_FREQ:
                pool.add(it["tag"])
    variants = {t for t in raw if isinstance(raw.get(t), dict) and F(t) >= MIN_FREQ
                and (RE_OWN.search(t) or RE_OTH.search(t))}
    added = variants - pool
    pool |= variants

    # 다른 축이 이미 가져간 태그는 뺀다(표정/의상/특징).
    taken: set[str] = set()
    for p in OUT.glob("*.txt"):
        if p.stem.startswith("pose_"):
            continue
        taken |= {l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()}
    pool -= taken

    # LLM 합의(기존 결과 재사용)
    cx = parse_classification((SCRATCH / "pose_codex_full.md").read_text(encoding="utf-8"))
    sb = parse_classification((SCRATCH / "pose_sub_full.md").read_text(encoding="utf-8"))

    # own/another's 변형이 둘 다 존재하는 개념 -> 우산 태그 제외 대상
    concepts_own = {base_concept(t) for t in pool if RE_OWN.search(t)}
    concepts_oth = {base_concept(t) for t in pool if RE_OTH.search(t)}
    ambiguous_umbrella = concepts_own & concepts_oth

    try:
        measured = json.loads(MEASURED_PATH.read_text(encoding="utf-8"))["verdict"]
    except (OSError, ValueError, KeyError):
        measured = {}

    slot: dict[str, str] = {}
    why: dict[str, str] = {}
    for t in sorted(pool):
        m = measured.get(t)
        if m:
            slot[t] = m["slot"]
            sh = f"{m['share']:.1%}" if m.get("share") is not None else "0건"
            why[t] = f"원본 쿼리 solo {sh}"
            continue
        if RE_NSFW.search(t):
            slot[t] = "nsfw"; why[t] = "성인 축 담당"
            continue
        if RE_OWN.search(t):
            slot[t] = "individual"; why[t] = "이름에 own"
            continue
        if RE_OTH.search(t):
            slot[t] = "global"; why[t] = "이름에 another's"
            continue
        if t in ambiguous_umbrella:
            slot[t] = "drop"
            why[t] = ("데이터가 변형 사용을 지시" if RE_REDIRECT.search(D(t))
                      else "own/another's 변형이 둘 다 있어 모호")
            continue
        e = ev.lookup(t)
        if e.hint_measured:
            slot[t] = slot_of(e.hint_measured)
            why[t] = f"실측 solo {e.solo_share:.1%} ({e.posts:,}건)"
            continue
        c, s = cx.get(t), sb.get(t)
        if c == "DROP" and s == "DROP":
            slot[t] = "drop"; why[t] = "LLM 2인 DROP"
            continue
        votes = [v for v in (c, s) if v and v != "DROP"]
        if not votes:
            slot[t] = "drop"; why[t] = "판정 없음"
            continue
        cnt = Counter("global" if v == "MULTI" else "individual" for v in votes)
        top, n = cnt.most_common(1)[0]
        slot[t] = top
        why[t] = f"LLM {n}/{len(votes)}" + ("" if n == len(votes) else " (갈림)")

    files = {"individual": "pose_solo", "global": "pose_multi",
             "drop": "pose_drop", "nsfw": "pose_nsfw"}
    for k, fn in files.items():
        tags = sorted([t for t, v in slot.items() if v == k], key=lambda t: -F(t))
        (OUT / f"{fn}.txt").write_text("\n".join(tags) + "\n", encoding="utf-8")
        print(f"  {fn}.txt {len(tags):5d}")

    # 표시 이름 사전: 개별 슬롯은 own 을 지운다.
    disp = {t: strip_own(t) for t, v in slot.items()
            if v == "individual" and RE_OWN.search(t)}
    (OUT / "_pose_display.json").write_text(
        json.dumps(disp, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n풀 {len(pool)}개 (own/another's 로 새로 편입 {len(added & pool)})")
    print("근거 분포:", dict(Counter(w.split("(")[0].split()[0] for w in why.values())))
    print(f"모호 우산 제외: {sum(1 for t in slot if slot[t]=='drop' and t in ambiguous_umbrella)}개")
    print(f"표시 이름 치환: {len(disp)}개")
    unresolved = [t for t in slot if why[t].endswith("(갈림)")]
    print(f"사람 확인 필요: {len(unresolved)}개 {unresolved[:10]}")
    (SCRATCH / "pose_slot_why.json").write_text(
        json.dumps(why, ensure_ascii=False, indent=0), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
