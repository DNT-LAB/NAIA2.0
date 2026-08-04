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


# `git checkout` 은 **추적되는 파일만** 되돌린다. 그런데 빌더 7개가
# `wildcards/thumb/_todo/` 에도 쓰고, 그 폴더는 gitignore 라 추적되지 않는다.
# 그래서 이 검사를 한 번 돌릴 때마다 '생성 대기 목록'이 축 전체 목록으로 덮여
# 있었다 — `thumb_manifest.py` 가 그것을 읽어 대기 4,825장이라는 헛수를 냈다.
# 추적 안 되는 파일은 손으로 떠 두었다가 손으로 되돌린다.
_UNTRACKED_SNAP: dict[str, bytes] = {}


def untracked_files() -> list[str]:
    out = git("ls-files", "--others", "--exclude-standard", "--ignored",
              "--directory", "--no-empty-directory", WILDCARDS)
    # gitignore 로 통째로 무시되는 폴더는 목록 대신 폴더명이 온다 — 직접 훑는다.
    paths: list[str] = []
    for d in out.stdout.decode("utf-8", "replace").splitlines():
        d = d.strip()
        if not d:
            continue
        p = ROOT / d
        if p.is_dir():
            paths += [str(q.relative_to(ROOT)).replace("\\", "/")
                      for q in p.rglob("*") if q.is_file()]
        elif p.is_file():
            paths.append(d)
    return paths


def snapshot_untracked() -> None:
    _UNTRACKED_SNAP.clear()
    for rel in untracked_files():
        try:
            _UNTRACKED_SNAP[rel] = (ROOT / rel).read_bytes()
        except OSError:
            pass


def restore() -> None:
    git("checkout", "--", WILDCARDS)
    for rel, blob in _UNTRACKED_SNAP.items():
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists() or p.read_bytes() != blob:
            p.write_bytes(blob)
    # 빌더가 **새로 만든** 추적 안 되는 파일도 지운다(원래 없던 것이다).
    for rel in untracked_files():
        if rel not in _UNTRACKED_SNAP:
            (ROOT / rel).unlink(missing_ok=True)


def dirty() -> list[str]:
    out = git("status", "--porcelain", "--", WILDCARDS).stdout.decode("utf-8", "replace")
    return [l for l in out.splitlines() if l.strip()]


# 은퇴의 판정 근거는 **실행 가드 호출**이다. 산문 배너로 판정하면 문구를 다듬는
# 순간 은퇴가 풀린다(배너는 사람용, 가드는 기계용). 배너만 있고 가드가 없는 파일은
# `문구만 은퇴` 로 잡아 실패시킨다 — 오늘 Codex 가 지적한 구멍이 정확히 그것이다.
RETIRED_GUARD = "retired_guard("
RETIRED_BANNER = "이 빌더는 **그냥 돌리면 안 된다.**"


def _src(script: str) -> str:
    p = ROOT / "tools" / script
    return p.read_text(encoding="utf-8") if p.exists() else ""


def is_retired(script: str) -> bool:
    """실행 가드가 박힌 빌더인가.

    은퇴 빌더의 소실은 **이미 알려진 상태**다 — 그래서 가드를 박았다. 실패로 세면
    이 검사가 항상 빨간불이라 게이트로 못 쓴다. 목록을 따로 두지 않고 파일에서
    읽는다(두 군데 적으면 갈라진다).
    """
    return RETIRED_GUARD in _src(script)


def banner_without_guard(script: str) -> bool:
    """은퇴라고 써 놓고 실제로는 아무나 돌릴 수 있는 상태인가."""
    s = _src(script)
    return RETIRED_BANNER in s and RETIRED_GUARD not in s


def run_builder(script: str) -> tuple[bool, str]:
    # 은퇴 빌더는 `tools/_retired_guard.py` 가 실행을 막는다. 무엇이 사라지는지 재는
    # 것이 이 도구의 일이고 직후에 되돌리므로, 여기서만 자물쇠를 연다.
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               NAIA_AXIS_BUILDER_UNLOCK="1")
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
    # 추적되지 않는 산출물(`_todo/` 의 생성 대기 목록)은 git 이 못 되돌린다.
    snapshot_untracked()

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
    # 배너만 있고 가드가 없으면 은퇴가 아니라 **은퇴한 척**이다. 그 상태로는 직접
    # 호출 한 번에 분류가 롤백되고, 이 검사는 소실을 예상된 것으로 넘겨 버린다.
    fake = [s for s, _l in BUILDERS if banner_without_guard(s)]
    if fake:
        print(f"!! 은퇴 배너만 있고 실행 가드가 없다: {', '.join(fake)}\n"
              f"   tools/_retired_guard.py 의 retired_guard() 를 첫머리에 넣어라.",
              file=sys.stderr)
        fail = True
    if dirty():
        print("경고: 검사 뒤에도 `wildcards/` 가 깨끗하지 않다. git status 를 확인하라.",
              file=sys.stderr)
        return 2
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
