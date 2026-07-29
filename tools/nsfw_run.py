# -*- coding: utf-8 -*-
"""성인 축 순차 실행기 — 목록 준비 · 생성 · 팩 반영을 한 번에.

`thumb_bench.py` 를 직접 쓰면 매번 세 가지를 손으로 해야 한다:
  1. `wildcards/nsfw/<분류>.txt` 를 `wildcards/thumb/_todo/` 로 복사
  2. 이미 만든 것을 빼기 (안 빼면 다시 만들어 예산을 먹는다)
  3. 생성 후 `build_interactive_thumbnails.py` 로 팩에 반영
이 셋을 묶고, 중단·재개가 되게 한다.

## 쓰는 법

    python tools/nsfw_run.py --list              # 분류별 진행 상태만 본다
    python tools/nsfw_run.py --all               # 남은 것 전부 순차 실행
    python tools/nsfw_run.py nsfw_genital        # 하나만
    python tools/nsfw_run.py --all --dry-run     # 프롬프트만 확인(요청 안 보냄)
    python tools/nsfw_run.py --pack              # 이미 만든 것을 팩에 반영만

중간에 끊어도 안전하다 — 다시 돌리면 **팩에 없는 것만** 큐에 올린다.

## 안전장치는 그대로 산다

`thumb_bench.py` 의 가드를 그대로 통과한다(어린 외형 태그 · `mature female` 누락 ·
등급 누락 · 은닉 3종 누락 -> 생성 거부). 이 스크립트는 그걸 우회하지 않는다.
아래 `BLOCKED` 는 그 위에 더하는 목록이다.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NSFW = ROOT / "wildcards" / "nsfw"
TODO = ROOT / "wildcards" / "thumb" / "_todo"
PACK = ROOT / "data" / "interactive_thumbnails.json"
OUTDIR = ROOT / "user-data" / "output" / "nsfw"
# 팩에 넣을 폴더. `q_run` 은 이 스크립트가 생기기 전에 만든 questionable 145장이다 —
# 같은 시드·같은 베이스라 새 폴더와 섞여도 결과가 같다(뒤에 넣은 쪽이 이긴다).
PACK_DIRS = [ROOT / "user-data" / "output" / "q_run", OUTDIR]

# 실행 순서 — 등급이 낮은 쪽부터. 중간에 멈춰도 덜 곤란한 순서다.
ORDER = [
    # questionable
    "nsfw_exposure", "nsfw_breast", "nsfw_butt", "nsfw_bondage",
    # explicit
    "nsfw_nipple", "nsfw_pubic", "nsfw_fluid", "nsfw_genital",
]

# 목록에서 빼는 것. `thumb_bench` 가드가 잡는 것과 별개로 여기서 미리 거른다.
#   oppai loli — 체형 축으로 이관됐다(외모 서술). 성인 도감에는 이제 없다.
#   diaper     — 성적 맥락에서 유아화로 읽힌다.
#   재갈류     — 얼굴이 있어야 성립해 은닉 사양(faceless)과 모순된다. 만들어도 안 보인다.
BLOCKED = {"oppai loli", "diaper"}
BLOCKED_RE = re.compile(r"\bgag\b|gagged")


def loaded_pack() -> set[str]:
    if not PACK.exists():
        return set()
    return set(json.loads(PACK.read_text(encoding="utf-8")))


def tags_of(batch: str) -> list[str]:
    f = NSFW / f"{batch}.txt"
    if not f.exists():
        return []
    return [l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


def pending(batch: str, pack: set[str]) -> tuple[list[str], list[str], list[str]]:
    """(남은 것, 이미 만든 것, 제외한 것)"""
    todo, done, skip = [], [], []
    for t in tags_of(batch):
        if t in BLOCKED or BLOCKED_RE.search(t):
            skip.append(t)
        elif f"{batch}/{t}" in pack:
            done.append(t)
        else:
            todo.append(t)
    return todo, done, skip


def run(cmd: list[str]) -> int:
    print(f"\n$ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, cwd=ROOT).returncode


def do_pack(py: str) -> int:
    """생성분을 팩에 넣고 프론트 모듈까지 다시 만든다.
    이 셋을 따로 하면 꼭 하나를 빠뜨린다(실제로 그래서 145장이 팩에 안 들어가 있었다)."""
    for d in PACK_DIRS:
        if not d.exists():
            print(f"  (건너뜀: {d.name} 없음)")
            continue
        if run([py, "tools/build_interactive_thumbnails.py", str(d)]) != 0:
            return 1
    if run([py, "tools/thumb_axes_emit.py"]) != 0:
        return 1
    pack = loaded_pack()
    left = sum(len(pending(b, pack)[0]) for b in ORDER)
    tail = f"남은 것 {left}장" if left else "완료"
    print(f"\n팩 {len(pack)}키 / 성인 축 {tail}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="성인 축 순차 실행기")
    ap.add_argument("batches", nargs="*", help=f"분류 이름 (없으면 --all/--list 사용). {ORDER}")
    ap.add_argument("--all", action="store_true", help="남은 분류를 순서대로 전부")
    ap.add_argument("--list", action="store_true", help="진행 상태만 출력")
    ap.add_argument("--dry-run", action="store_true", help="프롬프트만 출력(요청 안 보냄)")
    ap.add_argument("--pack", action="store_true", help="생성분을 팩에 반영만 하고 끝낸다")
    ap.add_argument("--no-pack", action="store_true", help="생성 후 팩 반영을 건너뛴다")
    ap.add_argument("--limit", type=int, default=0, help="분류당 최대 장수(시험용)")
    args = ap.parse_args()

    pack = loaded_pack()
    py = sys.executable

    if args.pack:
        return do_pack(py)

    if args.list or not (args.batches or args.all):
        print(f"{'분류':<16}{'전체':>6}{'완료':>6}{'남음':>6}{'제외':>6}   등급")
        tot = 0
        for b in ORDER:
            t, d, s = pending(b, pack)
            tier = "explicit" if b in ("nsfw_genital", "nsfw_fluid",
                                       "nsfw_nipple", "nsfw_pubic") else "questionable"
            print(f"{b:<16}{len(t)+len(d)+len(s):>6}{len(d):>6}{len(t):>6}{len(s):>6}   {tier}")
            tot += len(t)
        print(f"\n남은 총량 {tot}장")
        if not args.list:
            print("\n실행: python tools/nsfw_run.py --all")
        return 0

    targets = ORDER if args.all else args.batches
    unknown = [b for b in targets if b not in ORDER]
    if unknown:
        print(f"!! 모르는 분류: {unknown}\n   가능: {ORDER}")
        return 2

    for b in targets:
        todo, done, skip = pending(b, pack)
        if args.limit:
            todo = todo[:args.limit]
        if not todo:
            print(f"\n[{b}] 남은 것 없음 (완료 {len(done)} / 제외 {len(skip)})")
            continue
        print(f"\n[{b}] {len(todo)}장 (완료 {len(done)} / 제외 {len(skip)})")
        TODO.mkdir(parents=True, exist_ok=True)
        (TODO / f"{b}.txt").write_text("\n".join(todo) + "\n", encoding="utf-8")

        cmd = [py, "tools/thumb_bench.py", b, "--out", str(OUTDIR)]
        if args.dry_run:
            cmd.append("--dry-run")
        rc = run(cmd)
        if rc != 0:
            print(f"\n!! [{b}] 중단(코드 {rc}). 여기까지는 팩에 반영된다.")
            break

    if not args.dry_run and not args.no_pack:
        do_pack(py)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
