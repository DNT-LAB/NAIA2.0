# -*- coding: utf-8 -*-
"""조언 카드 '함께 쓰는 것' 의 데이터 불변식을 검사한다.

## 왜 필요한가

이 카드는 오래 **대부분의 태그에서 안 떴다.** 근거가 의상 전용 통계표 하나뿐이라
축 태그 12,149개 중 10,642개(88%)에 추천이 없었고, `job` 47/47 · `expression`
121/121 처럼 축이 통째로 비어 있었다(2026-08-13 실측). 그런데 **아무 에러도 안 났다** —
데이터가 없으면 카드가 조용히 사라지는 구조이기 때문이다.

같은 이유로 이 파일이 릴리즈 매니페스트에서 빠져 있어도 아무도 몰랐다. 배포판에는
파일 자체가 없었고 조언 카드가 통째로 죽어 있었다.

그래서 조용히 죽는 것을 **실행 코드로** 막는다.

## 쓰는 법

    python tools/check_tag_harmony.py
    python tools/check_tag_harmony.py --json

불변식이 깨지면 exit 1.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERAL = ROOT / "data" / "interactive_tag_harmony.json"
CLOTHING = ROOT / "data" / "interactive_clothing_harmony.json"
AXES = ROOT / "data" / "interactive_axis_tags.json"
THUMBS = ROOT / "data" / "interactive_thumbnails.json"
NSFW_DIR = ROOT / "wildcards" / "nsfw"

# 실측으로 잡은 하한. 지금 값은 93% / 후보 2,414종 / 그룹 15개다.
# 여유를 두되, 통째로 비는 사고(88% 결측)는 반드시 걸리게 잡는다.
MIN_AXIS_COVERAGE = 0.85
MIN_SEEDS = 9_000
MIN_GROUPS = 8
# 축이 통째로 비면 그건 데이터가 아니라 배선 사고다(job 47/47 이 그랬다).
MAX_EMPTY_AXES = 0


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    bad: list[str] = []
    stats: dict[str, object] = {}

    for p in (GENERAL, CLOTHING, AXES):
        if not p.exists():
            bad.append(f"파일이 없다: {p.relative_to(ROOT).as_posix()}")
    if bad:
        print("\n".join("  !! " + b for b in bad))
        return 1

    g = _load(GENERAL)
    rec = g.get("recommend") or {}
    grp = g.get("group") or {}
    labels = g.get("groupLabels") or {}
    axes = _load(AXES)["axes"]
    axis_tags = {t for v in axes.values() for t in v}

    stats["seeds"] = len(rec)
    stats["edges"] = sum(len(v) for v in rec.values())
    stats["groups"] = len(labels)
    if len(rec) < MIN_SEEDS:
        bad.append(f"씨앗이 {len(rec)}개뿐이다 (하한 {MIN_SEEDS})")
    if len(labels) < MIN_GROUPS:
        bad.append(f"그룹이 {len(labels)}개뿐이다 (하한 {MIN_GROUPS})")

    covered = sum(1 for t in axis_tags if rec.get(t))
    ratio = covered / max(1, len(axis_tags))
    stats["axisCoverage"] = round(ratio, 4)
    if ratio < MIN_AXIS_COVERAGE:
        bad.append(f"축 태그 커버리지 {ratio:.0%} (하한 {MIN_AXIS_COVERAGE:.0%})")

    empty = sorted(ax for ax, ts in axes.items()
                   if ts and not any(rec.get(t) for t in ts))
    stats["emptyAxes"] = empty
    if len(empty) > MAX_EMPTY_AXES:
        bad.append(f"추천이 하나도 없는 축 {len(empty)}개: {empty[:6]}")

    # 후보는 전부 축 어휘여야 한다 — 아니면 묶을 그룹이 없고, 축 밖에는
    # 메타 잡음과 성인 어휘 인접 태그가 섞인다.
    cands = {t for v in rec.values() for t in v}
    off = sorted(cands - axis_tags)
    stats["candidates"] = len(cands)
    if off:
        bad.append(f"축 밖 후보 {len(off)}개: {off[:6]}")
    missing_group = sorted(cands - set(grp))
    if missing_group:
        bad.append(f"그룹이 없는 후보 {len(missing_group)}개: {missing_group[:6]}")
    unknown_group = sorted({grp[t] for t in cands if t in grp} - set(labels))
    if unknown_group:
        bad.append(f"라벨 없는 그룹 {len(unknown_group)}개: {unknown_group[:6]}")

    # 성인 후보는 성인 씨앗에만. 일반 태그를 고른 사용자에게 성인 태그를 권하지 않는다.
    adult: set[str] = set()
    if NSFW_DIR.exists():
        for f in NSFW_DIR.glob("nsfw_*.txt"):
            adult |= {l.strip() for l in f.read_text(encoding="utf-8").splitlines()
                      if l.strip()}
    leak = [(a, b) for a, v in rec.items() if a not in adult
            for b in v if b in adult]
    stats["adultLeak"] = len(leak)
    if leak:
        bad.append(f"성인 후보가 일반 씨앗에 붙었다 {len(leak)}건: {leak[:4]}")

    # 그림 없는 후보는 카드에서 조용히 사라진다(recThumbsHtml). 머리말만 남는
    # 빈 카드의 원인이므로 여기서 센다.
    if THUMBS.exists():
        keys = set(_load(THUMBS))
        have = {k.split("/", 1)[1] if "/" in k else k for k in keys}
        nothumb = sorted(cands - have)
        stats["noThumb"] = len(nothumb)
        if nothumb:
            bad.append(f"썸네일 없는 후보 {len(nothumb)}개: {nothumb[:6]}")

    # 의상 층이 우선이라는 계약. 의상 씨앗의 추천은 의상 층이 낸다.
    c = _load(CLOTHING)
    stats["clothingSeeds"] = len(c.get("recommend") or {})

    if args.json:
        print(json.dumps({"stats": stats, "violations": bad},
                         ensure_ascii=False, indent=1))
    else:
        print(f"씨앗 {stats['seeds']:,} / 간선 {stats['edges']:,} / 후보 어휘 "
              f"{stats['candidates']:,} / 그룹 {stats['groups']}")
        print(f"축 태그 커버리지 {ratio:.0%} · 빈 축 {len(empty)}개 · "
              f"성인 누수 {stats['adultLeak']}건 · 썸네일 없음 {stats.get('noThumb', '?')}개")
        print(f"의상 층 씨앗 {stats['clothingSeeds']:,} (이쪽이 우선)")
        for b in bad:
            print(f"  !! {b}")
        if bad:
            print("\n데이터를 다시 구우려면:")
            print("  python tools/thumb_axes_emit.py          # 축 라벨")
            print("  python tools/build_tag_cooccurrence.py   # 동반 통계 + 조언 산출물")
        else:
            print("불변식 이상 없음.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
