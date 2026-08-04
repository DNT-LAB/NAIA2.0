# -*- coding: utf-8 -*-
"""현재 축 분류를 JSON 한 파일로 캡처한다.

## 왜

축 .txt 는 파일이 100개 넘게 흩어져 있고 gitignore 안에 있다(추적은 되지만 새 파일이
자동으로 안 잡힌다). 분류가 어긋났을 때 "원래 어땠는지"를 확인하려면 여러 커밋을
오가며 파일마다 비교해야 한다. 한 파일로 찍어 두면 diff 한 번으로 끝난다.

빌더를 은퇴시키기(=.txt 를 SSOT 로 선언) 전에 남기는 **안전망**이기도 하다.
빌더가 더는 분류를 재생성하지 못하므로, 사람이 실수로 지웠을 때 되돌릴 근거가 필요하다.

## 쓰는 법

    python tools/snapshot_axis_classification.py           # 갱신
    python tools/snapshot_axis_classification.py --check   # 어긋났는지만 확인(exit 1)

분류를 바꾼 커밋에서는 이 파일도 함께 갱신하라. `--check` 로 잊었는지 알 수 있다.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "interactive_axis_snapshot.json"
SRC_DIRS = ("wildcards/thumb", "wildcards/nsfw")


def wired_axes() -> set[str]:
    """화면에 실제로 나오는 축. 생성물 `interactiveAxes.mjs` 의 `ref:` 가 근거다."""
    import re
    p = ROOT / "app/web/remote/js/features/interactiveAxes.mjs"
    if not p.exists():
        return set()
    return set(re.findall(r'ref: "([a-z0-9_]+)"', p.read_text(encoding="utf-8")))


def collect() -> dict:
    axes: dict[str, dict] = {}
    for rel in SRC_DIRS:
        base = ROOT / rel
        if not base.exists():
            continue
        for path in sorted(base.glob("*.txt")):
            if path.stem.startswith("_"):
                continue          # 기록·제외 대장은 분류가 아니다
            tags = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
                    if l.strip()]
            axes[path.stem] = {
                # 폴더가 곧 블러 정책이다 — nsfw/ 에 있으면 성인 축으로 취급된다.
                "dir": rel.split("/")[-1],
                "count": len(tags),
                "tags": tags,
            }
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    # 화면에 배선된 축만 겹침 판정에 쓴다. `pose_solo`·`pose_multi` 같은 집계축은
    # 개별 축을 그대로 미러링하므로 전부 '겹침'으로 잡히는데, 그건 설계다.
    # 실제로 빈칸을 만드는 것은 **배선된 축 둘**이 같은 태그를 가질 때다
    # (팩 키가 `<축>/<태그>` 하나뿐이라 뒤쪽은 영영 안 찬다).
    wired = wired_axes()
    dup: dict[str, list[str]] = {}
    for name, info in axes.items():
        if wired and name not in wired:
            continue
        for t in info["tags"]:
            dup.setdefault(t, []).append(name)
    overlaps = {t: v for t, v in sorted(dup.items()) if len(v) > 1}
    return {
        "commit": head,
        "axis_count": len(axes),
        "tag_count": sum(a["count"] for a in axes.values()),
        "wired_axis_count": len(wired),
        "overlaps": overlaps,
        "axes": axes,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    snap = collect()
    body = json.dumps(snap, ensure_ascii=False, indent=1) + "\n"

    if args.check:
        if not OUT.exists():
            print("스냅샷이 없다 — 먼저 인자 없이 실행하라.", file=sys.stderr)
            return 1
        old = json.loads(OUT.read_text(encoding="utf-8"))
        diff = 0
        for name in sorted(set(old["axes"]) | set(snap["axes"])):
            a = set(old["axes"].get(name, {}).get("tags", []))
            b = set(snap["axes"].get(name, {}).get("tags", []))
            if a != b:
                diff += 1
                lost, gain = sorted(a - b), sorted(b - a)
                print(f"  {name}: 사라짐 {len(lost)} / 새로 {len(gain)}")
                if lost:
                    print(f"      사라짐: {', '.join(lost[:8])}"
                          + (" …" if len(lost) > 8 else ""))
                if gain:
                    print(f"      새로  : {', '.join(gain[:8])}"
                          + (" …" if len(gain) > 8 else ""))
        if diff:
            print(f"\n스냅샷과 다른 축 {diff}개 — 분류를 바꿨다면 스냅샷도 갱신하라.")
            return 1
        print(f"스냅샷과 일치 (축 {snap['axis_count']} · 태그 {snap['tag_count']})")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(body, encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"저장: {OUT.relative_to(ROOT)}  ({kb:.0f} KB)")
    print(f"  축 {snap['axis_count']}개 · 태그 {snap['tag_count']}개 · commit {snap['commit'][:8]}")
    if snap["overlaps"]:
        print(f"  ⚠ 두 축에 걸친 태그 {len(snap['overlaps'])}개 "
              f"(팩 키가 하나뿐이라 뒤쪽은 빈칸이 된다):")
        for t, where in list(snap["overlaps"].items())[:10]:
            print(f"      {t}  ->  {', '.join(where)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
