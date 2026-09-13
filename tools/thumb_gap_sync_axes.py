# -*- coding: utf-8 -*-
"""`_todo/` 에만 들어간 태그를 **축 파일에도** 넣는다(1회성 보정).

## 왜 필요했나

`thumb_gap_queue.py --write` 가 생성 큐(`_todo/<축>.txt`)에만 썼다. 그런데 팩 빌더
(`build_interactive_thumbnails.py`)는 PNG 메타데이터의 `2::<태그> ::` 를 뽑아
**축 파일** `wildcards/thumb/<축>.txt` 에서 소속을 찾는다. 큐에만 있고 축 파일에 없으면
그림을 3,385장 만들어 놓고도 전부 "가중치 블록에 축 태그 없음" 으로 분류 실패한다
(2026-09-13 실측).

같은 유형이 이 저장소에서 반복됐다 — `thumb_clothing_build` 가 축을 계산만 하고
`.txt` 로 안 써서 코드와 파일이 갈라졌던 것과 같다. **큐와 축 파일은 성격이 다르다**:
축 파일은 "이 태그는 이 축 소속" 이라는 사실이고, 큐는 "아직 안 만들었다" 는 상태다.

## 무엇을 하나

`_todo/<축>.txt` 의 태그 중 `<축>.txt` 에 없는 것만 뒤에 덧붙인다. 중간 산출물
(`pose_solo`·`pose_multi`·`pose_drop`·`expression_from_pose`)은 축이 아니므로 건너뛴다.

    python tools/thumb_gap_sync_axes.py --dry
    python tools/thumb_gap_sync_axes.py --write
"""
from __future__ import annotations

import argparse
import io
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THUMB = ROOT / "wildcards" / "thumb"
TODO = THUMB / "_todo"
NOT_AXES = {"pose_solo", "pose_multi", "pose_drop", "expression_from_pose"}


def lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    total = 0
    plan: list[tuple[Path, list[str], int]] = []
    for todo_path in sorted(TODO.glob("*.txt")):
        axis = todo_path.stem
        if axis in NOT_AXES:
            print(f"  건너뜀(중간 산출물): {axis}")
            continue
        axis_path = THUMB / f"{axis}.txt"
        if not axis_path.exists():
            print(f"  !! 축 파일이 없다: {axis_path.name} — 손으로 확인 필요")
            continue
        have = set(lines(axis_path))
        new = [t for t in lines(todo_path) if t not in have]
        if new:
            plan.append((axis_path, new, len(have)))
            total += len(new)

    for axis_path, new, before in plan:
        print(f"  {axis_path.name:<24} {before:>4} -> {before + len(new):<4} (+{len(new)})")
    print(f"\n축 {len(plan)}개 / 태그 {total}개 추가 대상")

    if not args.write:
        print("(--write 를 주지 않아 아무것도 쓰지 않았습니다)")
        return 0

    for axis_path, new, before in plan:
        # ⚠️ 줄바꿈을 고정하고 임시 파일 + os.replace 로 쓴다. Windows 기본 쓰기는
        #    \n -> \r\n 으로 바꿔 파일 전체가 바뀐 diff 를 만든다(이 저장소 전례).
        current = axis_path.read_text(encoding="utf-8")
        if current and not current.endswith("\n"):
            current += "\n"
        tmp = axis_path.with_suffix(".txt.tmp")
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(current + "\n".join(new) + "\n")
        os.replace(tmp, axis_path)
        after = len(lines(axis_path))
        assert after == before + len(new), (axis_path.name, before, len(new), after)
    print(f"\n{total}개 추가 완료. 다음: build_interactive_thumbnails.py 재실행")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
