# -*- coding: utf-8 -*-
"""예전 두 파일 색인(sqlite + records.bin)을 **한 파일(.naiamap)** 로 바꾼다. 다시 빌드하지 않는다.

사용법
    python tools/pack_event_map_index.py --index <event_map.sqlite3> [--out <event_map.naiamap>]

    예) python tools/pack_event_map_index.py --index "C:\\VNR\\DEV\\NAIA-Event-Map-Build\\v2\\event_map.sqlite3"
        -> 같은 폴더에 event_map.naiamap 이 생긴다.

    - 1분 안팎(대부분 파일 복사). 원본 두 파일은 읽기만 하고 지우지 않는다.
    - 이미 결과가 있으면 쓰지 않는다. 끊기면 `*.part` 만 남고 다음 실행이 치운다.
    - `--compare` 를 주면 끝나고 원본과 **내용이 같은지** 대조한다(태그표 · 게시물 목록 ·
      본문 · 분면표 · 시험 질의). 기본은 건너뛴다 - 확인은 시험대에서 직접 한다.
    - 태그 설명(영문 정의 등 JSON)은 옮기지 않는다 - 맵이 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from array import array
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from core.event_map import EventMapIndex  # noqa: E402
from core.event_map.pack import PackWriter, is_pack  # noqa: E402

CHUNK = 16 << 20        # 본문을 옮길 때 한 번에 쓰는 원소 수(uint16 기준 32MB)


def say(text: str) -> None:
    print(text, flush=True)


def convert(src: Path, out: Path) -> None:
    import numpy as np

    part = out.with_name(out.name + ".part")
    if part.exists():
        say("지난 실행이 남긴 %s 를 치운다" % part.name)
        part.unlink()
    idx = EventMapIndex(src)
    try:
        if idx._pack is not None:
            raise SystemExit("이미 한 파일 형식이다: %s" % src)
        t0 = time.perf_counter()
        pw = PackWriter(part)

        say("[1/3] 게시물 본문을 옮긴다 (%.0f MB)..." % (idx.body.size * 2 / 1048576))
        pw.begin("body")
        for a in range(0, idx.body.size, CHUNK):
            pw.write(np.ascontiguousarray(idx.body[a:a + CHUNK], dtype="<u2").tobytes())
        pw.end()
        pw.add("offsets", np.ascontiguousarray(idx.offsets, dtype="<u4").tobytes())
        # 분면표도 rid 로 색인한다 - 오프셋 표와 같은 길이로 맞춘다.
        parts = np.zeros(idx.offsets.size - 1, dtype=np.uint8)
        n = min(parts.size, idx.part_arr.size)
        parts[:n] = idx.part_arr[:n]
        pw.add("partitions", parts.tobytes())

        say("[2/3] 태그별 게시물 목록 %s개를 옮긴다..." % format(idx.n_tags, ","))
        post_index = array("Q", [0])
        pw.begin("postings")
        for tid in range(idx.n_tags):
            blob = idx.posting_blob(tid)
            pw.write(blob)
            post_index.append(post_index[-1] + len(blob))
        pw.end()
        if sys.byteorder != "little":
            post_index.byteswap()
        pw.add("post_index", post_index.tobytes())
        pw.add_json("tags", idx.tag_rows())
        meta = {k: v for k, v in idx.meta.items()
                if k not in ("record_body", "post_partitions")}
        meta["record_encoding"] = "uint16-le-flat"
        meta["converted_from"] = {"index": str(idx.path), "body": str(idx.body_path),
                                  "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        pw.add_json("meta", meta)
        pw.close()
    finally:
        idx.close()
    os.replace(part, out)
    say("      %.0f초" % (time.perf_counter() - t0))


def compare(src: Path, out: Path) -> None:
    """원본 두 파일과 새 한 파일이 **같은 색인**인지 대조한다."""
    import numpy as np

    say("[3/3] 원본과 대조...")
    a = EventMapIndex(src)
    b = EventMapIndex(out)
    try:
        problems = []
        if a.tag_rows() != b.tag_rows():
            problems.append("태그표가 다르다")
        if a.total_posts != b.total_posts or a.partitions != b.partitions:
            problems.append("게시물 수나 분면 목록이 다르다")
        if not np.array_equal(a.offsets, b.offsets):
            problems.append("오프셋 표가 다르다")
        if not np.array_equal(a.body, b.body):
            problems.append("게시물 본문이 다르다")
        n = min(a.part_arr.size, b.part_arr.size)
        if not np.array_equal(a.part_arr[:n], b.part_arr[:n]) or b.part_arr[n:].any():
            problems.append("분면표가 다르다")
        for tid in range(a.n_tags):
            if a.posting_blob(tid) != b.posting_blob(tid):
                problems.append("태그 %s 의 게시물 목록이 다르다" % a.by_id[tid])
                break
        for pins, kw in ((["armpits", "armpit crease"], {}), (["kiss"], {"ratings": ["e"]}),
                         (["stretching"], {"exclude": ["yoga"]})):
            ra, rb = a.explore(pins, limit=10, **kw), b.explore(pins, limit=10, **kw)
            if (ra["observed_posts"] != rb["observed_posts"]
                    or [c["tag"] for c in ra["candidates"]] != [c["tag"] for c in rb["candidates"]]):
                problems.append("시험 질의 %s 의 답이 다르다" % pins)
            sa, sb = a.sample(pins, n=5, seed=1, **kw), b.sample(pins, n=5, seed=1, **kw)
            if [s["prompt"] for s in sa["samples"]] != [s["prompt"] for s in sb["samples"]]:
                problems.append("시험 뽑기 %s 의 답이 다르다" % pins)
        if problems:
            for p in problems:
                say("      실패: " + p)
            raise SystemExit("대조 실패 - 새 파일을 쓰지 마라: %s" % out)
        say("      태그 %s개 · 게시물 목록 · 본문 %s엔트리 · 분면표 · 시험 질의 3개 - 전부 같다"
            % (format(a.n_tags, ","), format(int(a.body.size), ",")))
    finally:
        a.close()
        b.close()


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")     # cp949 콘솔에서도 죽지 않게
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="두 파일 색인을 한 파일(.naiamap)로 바꾼다")
    ap.add_argument("--index", required=True, help="예전 색인의 event_map.sqlite3 (옆에 records.bin 이 있어야 한다)")
    ap.add_argument("--out", help="만들 .naiamap 경로 (기본: 같은 폴더의 event_map.naiamap)")
    ap.add_argument("--compare", action="store_true",
                    help="끝나고 원본 두 파일과 내용이 같은지 대조한다(기본: 건너뜀)")
    args = ap.parse_args()

    src = Path(args.index).resolve()
    out = Path(args.out).resolve() if args.out else src.with_name("event_map.naiamap")
    if not src.is_file():
        raise SystemExit("색인이 없다: %s" % src)
    if is_pack(src):
        raise SystemExit("이미 한 파일 형식이다: %s" % src)
    if out.exists():
        raise SystemExit("이미 결과가 있다. 덮어쓰지 않는다: %s" % out)
    out.parent.mkdir(parents=True, exist_ok=True)

    say("원본 : %s" % src)
    say("출력 : %s" % out)
    convert(src, out)
    if args.compare:
        compare(src, out)
    else:
        say("[3/3] 원본 대조는 건너뛴다(--compare 로 켠다). 시험대에서 확인하라.")
    say("")
    say("완료  %s  %.1f MB" % (out, out.stat().st_size / 1048576))
    say("원본 두 파일은 그대로 두었다. 새 파일로 잘 돌면 지워도 된다.")
    say("")
    say("시험대 띄우기:")
    say('  python "%s" --index "%s"' % (REPO / "tools" / "event_map_playground.py", out))


if __name__ == "__main__":
    main()
