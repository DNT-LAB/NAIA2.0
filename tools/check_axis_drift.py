# -*- coding: utf-8 -*-
"""축 빌더가 커밋된 분류를 되돌리는지 검사한다.

## 왜 필요한가

`wildcards/**/<축>.txt` 는 **생성물**이다. 빌더가 축마다 파일을 통째로 덮어쓴다.
그런데 태그를 손으로 옮기는 일이 잦고(오분류 정리), 그 결과가 .txt 에만 남으면
다음 빌더 실행 한 번에 조용히 사라진다. 2026-08-03 하루에만 세 번 겪었다:

  - `interactiveAxes.mjs` 를 손으로 고침 -> `thumb_axes_emit.py` 가 되돌림
  - 축 .txt 를 손으로 고침         -> `thumb_axes_build.py` 가 30개 되돌림
  - 같은 건                         -> `thumb_view_build.py` 가 8개 되돌림

빌더를 하나씩 개조하는 대신 **검사 한 곳**을 둔다. 빌더를 사본이 아니라 제자리에서
돌리고(빌더들이 출력 경로를 인자로 받지 않는다) 곧바로 되돌린다 — 그래서 시작 전에
`wildcards/` 가 깨끗한지 확인하고, 무슨 일이 있어도 `git checkout` 으로 복구한다.

## 쓰는 법

    python tools/check_axis_drift.py            # 전부 검사
    python tools/check_axis_drift.py --json     # 기계용
    python tools/check_axis_drift.py --only thumb_view_build

커밋된 축에서 태그가 하나라도 사라지면 exit 1. 순서 변화와 **추가**는 통과다 —
빌더가 사전에서 새 태그를 끌어오는 것은 정상 동작이다.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WILDCARDS = "wildcards"

# 축 .txt 를 쓰는 빌더. 여기 없는 도구는 검사되지 않는다 — 새 빌더를 만들면 추가하라.
# (자동 탐지 대신 목록으로 두는 이유: `tools/` 에는 네트워크를 타거나 릴리즈를 만드는
#  스크립트도 있어 무작정 실행하면 안 된다.)
BUILDERS: list[tuple[str, str]] = [
    ("thumb_axes_build.py", "신체·얼굴·머리·표정·종족"),
    ("thumb_view_build.py", "구도(프레이밍·시점·화면구성)"),
    ("build_pose_axes.py", "자세"),
    ("thumb_clothing_build.py", "의상·소품"),
    ("build_object_axes.py", "사물"),
    ("build_location_axes.py", "배경·장소"),
    ("build_effect_axes.py", "효과·기호"),
    ("build_creature_axes.py", "동물"),
    ("thumb_meta_build.py", "기타·텍스트"),
]


def git(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=capture, text=False)


def tracked_axis_files() -> list[str]:
    out = git("ls-files", WILDCARDS).stdout.decode("utf-8", "replace")
    return [p for p in out.splitlines()
            if p.endswith(".txt") and not Path(p).name.startswith("_")]


def read_tags(rel: str) -> list[str]:
    p = ROOT / rel
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def head_tags(rel: str) -> list[str]:
    r = git("show", f"HEAD:{rel}")
    if r.returncode != 0:
        return []
    return [l.strip() for l in r.stdout.decode("utf-8", "replace").splitlines() if l.strip()]


def restore() -> None:
    git("checkout", "--", WILDCARDS)


def dirty() -> list[str]:
    out = git("status", "--porcelain", "--", WILDCARDS).stdout.decode("utf-8", "replace")
    return [l for l in out.splitlines() if l.strip()]


RETIRED_MARK = "이 빌더는 **그냥 돌리면 안 된다.**"


def is_retired(script: str) -> bool:
    """은퇴 배너가 박힌 빌더인가.

    은퇴 빌더의 소실은 **이미 알려진 상태**다 — 그래서 배너를 박았다. 실패로 세면
    이 검사가 항상 빨간불이라 게이트로 못 쓴다. 목록을 따로 두지 않고 파일에서
    읽는다(두 군데 적으면 갈라진다).
    """
    p = ROOT / "tools" / script
    return p.exists() and RETIRED_MARK in p.read_text(encoding="utf-8")


def run_builder(script: str) -> tuple[bool, str]:
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, f"tools/{script}"], cwd=ROOT,
                       capture_output=True, env=env)
    tail = r.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
    return r.returncode == 0, "\n".join(tail)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", default="", help="빌더 파일명 일부")
    args = ap.parse_args()

    if dirty():
        print("중단 — `wildcards/` 에 커밋되지 않은 변경이 있다.", file=sys.stderr)
        print("       이 검사는 빌더를 제자리에서 돌리고 git 으로 되돌린다.", file=sys.stderr)
        print("       먼저 커밋하거나 되돌린 뒤 다시 실행하라.", file=sys.stderr)
        for line in dirty():
            print("       " + line, file=sys.stderr)
        return 2

    files = tracked_axis_files()
    baseline = {rel: head_tags(rel) for rel in files}

    report: list[dict] = []
    try:
        for script, label in BUILDERS:
            if args.only and args.only not in script:
                continue
            if not (ROOT / "tools" / script).exists():
                report.append({"builder": script, "label": label,
                               "status": "없음", "lost": {}})
                continue
            ok, tail = run_builder(script)
            lost: dict[str, list[str]] = {}
            if ok:
                for rel, before in baseline.items():
                    after = set(read_tags(rel))
                    gone = [t for t in before if t not in after]
                    if gone:
                        lost[Path(rel).stem] = gone
            report.append({
                "builder": script, "label": label,
                "status": "ok" if ok else "실행 실패",
                "retired": is_retired(script),
                "error": "" if ok else tail,
                "lost": lost,
            })
            restore()
    finally:
        restore()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        bad = 0        # 은퇴하지 않은 빌더의 소실만 센다
        for r in report:
            n = sum(len(v) for v in r["lost"].values())
            if not r.get("retired"):
                bad += n
            clean = r["status"] == "ok" and not n
            mark = "  " if clean else ("··" if r.get("retired") else "!!")
            note = " · 은퇴(예상됨)" if (r.get("retired") and n) else ""
            print(f"{mark} {r['builder']:<26}{r['label']:<22}{r['status']}"
                  + (f" · 소실 {n}" if n else "") + note)
            if r["status"] == "실행 실패":
                for line in (r.get("error") or "").splitlines():
                    print(f"      {line}")
            for axis, tags in sorted(r["lost"].items()):
                head = ", ".join(tags[:8]) + (" …" if len(tags) > 8 else "")
                print(f"      {axis}: {len(tags)}개 — {head}")
        print()
        retired_n = sum(sum(len(v) for v in r["lost"].values())
                        for r in report if r.get("retired"))
        if bad:
            print(f"!! 살아 있는 빌더의 소실 {bad}개 — 명시 배정으로 옮겨라")
        else:
            print("살아 있는 빌더는 전부 커밋된 분류를 재현한다")
        if retired_n:
            print(f"   (은퇴 빌더 소실 {retired_n}개는 예상된 상태 — 각 파일 첫머리 참조)")

    # 은퇴 빌더의 소실은 실패가 아니다. **실행 실패는 은퇴 여부와 무관하게 실패다** —
    # 은퇴 배너를 넣다가 `from __future__` 앞에 docstring 을 끼워 파일을 깨뜨린 적이
    # 있고, 그것을 이 검사가 잡았다.
    fail = any((r["lost"] and not r.get("retired")) or r["status"] == "실행 실패"
               for r in report)
    if dirty():
        print("경고: 검사 뒤에도 `wildcards/` 가 깨끗하지 않다. git status 를 확인하라.",
              file=sys.stderr)
        return 2
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
