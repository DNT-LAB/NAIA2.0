# -*- coding: utf-8 -*-
"""`_todo/*.txt` 를 **완성된 프롬프트 한 줄씩** 담은 와일드카드로 펼친다.

## 왜 필요한가

`thumb_bench.py` 는 NAI 를 직접 호출해 배치를 돌린다. 그런데 한도·시간대 제약 때문에
사용자가 앱에서 직접 돌리는 편이 나은 경우가 있고, 그때 필요한 건 축별 템플릿이 아니라
**그냥 붙여 넣고 한 바퀴 돌릴 수 있는 줄 목록**이다(성인 축에서 168줄로 이미 한 번 했다).

한 줄 = 한 장. 베이스가 1girl 인 줄과 1boy 인 줄이 섞여 있어도 상관없다 — 각 줄이
완결된 프롬프트이기 때문이다. 와일드카드는 줄 단위로 뽑으므로 주석을 넣으면 안 된다.

프롬프트 조립은 `thumb_bench.build_prompt` 를 그대로 쓴다. 여기서 템플릿을 다시 적으면
벤치와 갈라져서, 사용자가 돌린 그림과 도구가 돌린 그림의 베이스가 달라진다.

## 사용

    python tools/thumb_todo_prompts.py                     # 배선된 축 전부
    python tools/thumb_todo_prompts.py --axes loc_backdrop fx_effect
    python tools/thumb_todo_prompts.py -o wildcards/thumb/_todo/_blanks.txt
"""
import argparse
import json
from pathlib import Path

import tools.thumb_bench as tb

TODO = Path("wildcards/thumb/_todo")
BENCH = Path("wildcards/thumb/_bench.json")
AXES_MJS = Path("app/web/remote/js/features/interactiveAxes.mjs")


def wired_axes() -> set[str]:
    """UI 가 실제로 그리는 축. 미배선 축(pose_solo·view_* 등)의 2,200장을 섞지 않는다.

    화면에 빈칸으로 보이는 것만 대상이라야 "빈칸을 채운다" 는 목적과 맞는다.
    출처는 emit 산출물이다 — 여기 손으로 적으면 슬롯을 바꿀 때 갈라진다.
    """
    if not AXES_MJS.exists():
        raise SystemExit(f"{AXES_MJS} 가 없다. tools/thumb_axes_emit.py 를 먼저 돌려라.")
    src = AXES_MJS.read_text(encoding="utf-8")
    import re
    return set(re.findall(r'ref:\s*"(\w+)"', src))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--axes", nargs="*", help="지정하면 그 축만(미배선 축도 허용)")
    ap.add_argument("-o", "--out", default="wildcards/thumb/_todo/_blanks.txt")
    args = ap.parse_args()

    bench = json.loads(BENCH.read_text(encoding="utf-8"))
    wired = None if args.axes else wired_axes()

    # `_todo/<batch>.txt` 의 stem 이 곧 배치 이름이다. `<axis>_male` 도 그렇게 들어온다.
    batches = sorted(p.stem for p in TODO.glob("*.txt") if not p.stem.startswith("_"))
    if args.axes:
        want = set(args.axes) | {f"{a}_male" for a in args.axes}
        batches = [b for b in batches if b in want]

    # 네거티브별로 파일을 나눈다. 와일드카드는 positive 만 담으므로, 네거티브가 다른 줄을
    # 한 파일에 섞으면 사용자가 어느 줄에 어느 네거티브를 써야 하는지 알 수 없다.
    # (`species_male` 은 furry 억제, `body_type_male` 은 adolescent 절 제거가 필요하다.)
    groups: dict[str, list[str]] = {}
    report: list[tuple[str, int]] = []
    skipped: list[tuple[str, str]] = []
    for batch in batches:
        # 남성 배치는 축 이름이 `<axis>_male` 이지만 화면 축은 `<axis>` 다.
        axis = batch[: -len("_male")] if batch.endswith("_male") else batch
        if wired is not None and axis not in wired and batch not in wired:
            skipped.append((batch, "미배선 축"))
            continue
        if batch not in bench["batches"]:
            skipped.append((batch, "_bench.json 에 배치 정의 없음"))
            continue
        tags = tb.batch_tags(batch, required=False)
        if not tags:
            continue
        for t in tags:
            pos, neg = tb.build_prompt(bench, batch, t)    # 연령 가드는 여기서 돈다
            groups.setdefault(neg, []).append(pos)
        report.append((batch, len(tags)))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 줄이 가장 많은 네거티브를 본 파일로, 나머지는 `-negN` 접미로 낸다.
    order = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    written: list[tuple[Path, int, str]] = []
    for i, (neg, lines) in enumerate(order):
        path = out if i == 0 else out.with_name(f"{out.stem}-neg{i + 1}{out.suffix}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        neg_path = path.with_name(f"{path.stem}.negative.txt")
        neg_path.write_text(neg + "\n", encoding="utf-8")
        written.append((path, len(lines), neg_path.name))

    for b, n in report:
        print(f"  {b:<18}{n:>4}장")
    for b, why in skipped:
        print(f"  (건너뜀) {b:<18}{why}")
    print()
    for path, n, neg_name in written:
        print(f"  {n:>3}줄 -> {path}   (네거티브: {neg_name})")
    print(f"\n총 {sum(n for _, n, _ in written)}줄 / 네거티브 {len(written)}종")


if __name__ == "__main__":
    main()
