# -*- coding: utf-8 -*-
"""127축 전수 감사 — 자세·성인 말고 **나머지 축이 괜찮은가**.

지금까지 전수로 잰 것은 두 축뿐이다:

    성인(723 태그)   진입 99.8% · 기권 0.0% · 위생처리 없음
    자세(36축 2,166) 프레이밍 오염 4.1% -> 0.0%, 1위 행 오염 49 -> 0

나머지 90여 축은 표본으로만 봤다. 자세 축에서 나온 세 가지 문제 유형이 다른
축에도 있는지 확인해야 한다:

    프레이밍 잔여   자세는 0으로 만들었지만 다른 축은 안 셌다
    작품 편향       `running -> horse ears`(우마무스메)처럼 캐릭터 필터를
                    우회하는 것. 사물·의상 축이 더 취약할 수 있다
    자기 축 반복    자세는 27.5%였는데 다른 축 수치는 모른다

## 축마다 재는 것

    진입률    축 태그 중 앵커가 된 비율
    기권률    앵커가 됐지만 커버리지 바닥(Policy.min_coverage)을 못 넘는 비율
    커버중앙  1위 행 커버리지의 중앙값
    자기반복  1위 행에 **같은 축** 태그가 낀 비율
    잔여오염  프레이밍/색이 아직 후보로 남아 있나 (0 이어야 한다)

## 쓰는 법

    python tools/audit_axis_coverage.py
    python tools/audit_axis_coverage.py --group 2girls --out audit.txt
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.tag_combo.noise import is_color_tag, is_framing_tag   # noqa: E402
from core.tag_combo.service import ComboService, resolve_dirs   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="축별 조합 추천 커버리지 감사")
    ap.add_argument("--group", default="1girl_solo")
    ap.add_argument("--min-tags", type=int, default=5,
                    help="태그가 이보다 적은 축은 통계가 무의미해 건너뛴다")
    ap.add_argument("--out", default="", help="결과를 파일로도 쓴다")
    args = ap.parse_args()

    lines: list[str] = []

    def w(msg: str = "") -> None:
        lines.append(msg)
        print(msg)

    ax = json.loads((ROOT / "data/interactive_axis_tags.json")
                    .read_text(encoding="utf-8"))["axes"]
    t, s = resolve_dirs(ROOT)
    svc = ComboService(t, search_dirs=s)
    bk = svc.bank()
    if bk is None:
        w("!! 레시피 뱅크가 없다. tools/build_recipe_bank.py 를 먼저 돌려라.")
        return 2
    tab = bk.anchors(args.group)
    if not tab:
        w(f"!! 뱅크에 그룹이 없다: {args.group}")
        return 2
    floor = svc.policy.min_coverage

    rows = []
    for axis, tags in ax.items():
        ts = {str(x).strip().lower() for x in tags}
        if len(ts) < args.min_tags:
            continue
        inb = [x for x in ts if x in tab and tab[x]]
        if not inb:
            rows.append({"axis": axis, "n": len(ts), "in": 0, "enter": 0.0,
                         "abst": 1.0, "med": 0.0, "self": 0.0, "dirty": 0.0,
                         "chips": 0})
            continue
        covs = [tab[x][0]["coverage"] for x in inb]
        shown = [c for c in covs if c >= floor]
        self_rep = sum(1 for x in inb if any(y in ts for y in tab[x][0]["tags"]))
        chips = [y for x in inb for r in tab[x][:3] for y in r["tags"]]
        dirty = sum(1 for c in chips if is_framing_tag(c) or is_color_tag(c))
        rows.append({
            "axis": axis, "n": len(ts), "in": len(inb),
            "enter": len(inb) / len(ts),
            "abst": 1 - (len(shown) / len(covs)),
            "med": st.median(covs), "self": self_rep / len(inb),
            "dirty": dirty / max(1, len(chips)), "chips": len(chips),
        })

    w(f"그룹 {args.group} · 축 {len(rows)}개 · 뱅크 앵커 {len(tab):,} "
      f"· 커버리지 바닥 {floor:.0%}")
    w("")
    w(f"{'축':<26} {'태그':>6} {'진입':>7} {'기권':>7} {'커버중앙':>9} "
      f"{'자기반복':>9} {'잔여오염':>9}")
    w("-" * 80)
    for r in sorted(rows, key=lambda x: x["enter"]):
        w(f"{r['axis']:<26} {r['n']:>6,} {r['enter']:>7.1%} {r['abst']:>7.1%} "
          f"{r['med']:>9.1%} {r['self']:>9.1%} {r['dirty']:>9.2%}")

    w("")
    w("=== 요약 (축별 값의 분포) ===")
    for key, label in (("enter", "진입률"), ("abst", "기권률"),
                       ("med", "커버중앙"), ("self", "자기반복"),
                       ("dirty", "잔여오염")):
        v = [r[key] for r in rows]
        w(f"   {label:<9} 중앙 {st.median(v):>7.1%} · 최소 {min(v):>7.1%} "
          f"· 최대 {max(v):>7.1%}")

    w("")
    w("=== 주의가 필요한 축 ===")
    w("진입률 하위 10 (앵커가 안 되는 축):")
    for r in sorted(rows, key=lambda x: x["enter"])[:10]:
        w(f"   {r['axis']:<26} {r['enter']:>7.1%} ({r['in']}/{r['n']})")
    w("기권률 상위 10 (답을 못 내는 축):")
    for r in sorted(rows, key=lambda x: -x["abst"])[:10]:
        w(f"   {r['axis']:<26} {r['abst']:>7.1%} · 커버중앙 {r['med']:.1%}")
    w("자기반복 상위 10 (동어반복 위험):")
    for r in sorted(rows, key=lambda x: -x["self"])[:10]:
        w(f"   {r['axis']:<26} {r['self']:>7.1%}")
    w("잔여오염 상위 5 (0 이어야 정상):")
    for r in sorted(rows, key=lambda x: -x["dirty"])[:5]:
        w(f"   {r['axis']:<26} {r['dirty']:>7.2%} ({r['chips']}칩)")

    if args.out:
        Path(args.out).write_text("\n".join(lines), encoding="utf-8")
        print(f"\n저장: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
