# -*- coding: utf-8 -*-
"""은퇴한 축 빌더를 **실행 시점에** 막는다.

## 왜 배너로는 부족한가

축 .txt 는 생성물이지만 손으로 고친 분류가 쌓여 **.txt 가 SSOT** 가 됐다. 그래서
빌더 7개를 은퇴시키고 파일 첫머리에 경고 배너를 넣었다. 그런데 배너는 사람에게
하는 말이지 자물쇠가 아니다 — 직접 호출 한 번이면 커밋된 분류가 그대로 롤백된다
(2026-08-04 Codex 리뷰 지적). 검사 도구(`check_axis_drift.py`)조차 은퇴 빌더의
소실을 '예상된 상태'로 넘기므로, 이 경로는 아무도 못 잡는다.

여기서 실제로 막는다. 은퇴 빌더는 이 가드를 통과하지 못하면 아무것도 쓰지 않고
exit 3 으로 끝난다.

## 통과하는 두 가지 경우

  1. `check_axis_drift.py` 가 돌릴 때 — 무엇이 사라지는지 재는 것이 그 도구의
     일이고, 어차피 직후에 `git checkout` 으로 되돌린다. 환경변수로 연다.
  2. 사람이 절차를 밟고 의도적으로 열 때:

         NAIA_AXIS_BUILDER_UNLOCK=1 python tools/build_pose_axes.py
         python tools/build_pose_axes.py --unlock

     열기 전에 `check_axis_drift.py --only <빌더>` 로 사라질 태그를 먼저 보고,
     그것을 빌더의 명시 배정에 옮겨라. 되돌릴 근거는
     `data/interactive_axis_snapshot.json` 에 있다.
"""
from __future__ import annotations

import os
import sys

ENV_UNLOCK = "NAIA_AXIS_BUILDER_UNLOCK"
FLAG_UNLOCK = "--unlock"


def retired_guard(script: str, lost: str = "") -> None:
    """은퇴 빌더 첫머리에서 호출한다. 잠겨 있으면 여기서 프로세스가 끝난다."""
    if os.environ.get(ENV_UNLOCK) == "1" or FLAG_UNLOCK in sys.argv:
        return
    hint = f" 지금 실행하면 {lost} 가 사라진다." if lost else ""
    # 콘솔이 cp949 일 수 있다 — 특수문자 없이 ASCII 기호만 쓴다.
    print(
        f"[막힘] {script} 는 은퇴한 빌더다. 축 .txt 가 SSOT 이므로 그냥 돌리면"
        f" 커밋된 분류가 롤백된다.{hint}\n"
        f"  먼저:  python tools/check_axis_drift.py --only {script.removesuffix('.py')}\n"
        f"  열려면: {ENV_UNLOCK}=1 python tools/{script}   (또는 {FLAG_UNLOCK})\n"
        f"  자세한 절차는 {script} 첫머리와 tools/_retired_guard.py 를 보라.",
        file=sys.stderr,
    )
    raise SystemExit(3)
