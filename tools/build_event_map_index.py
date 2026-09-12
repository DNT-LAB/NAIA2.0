# -*- coding: utf-8 -*-
"""이벤트 맵 색인 빌더. 원본에서 **맵이 실제로 쓰는 것만** 골라 파일 하나에 싼다.

사용법
    python tools/build_event_map_index.py --source <원본 DB> --out-dir <새 폴더>
        [--policy full|none] [--guard source|age|none] [--age-floor on|off] [--limit-rows N]

    예) 상용 후보(정책 전부 · 관측 DB)
      python tools/build_event_map_index.py ^
        --source "C:\\VNR\\DEV\\NAIA-Event-Map-Handoff-20260911\\coverage_expansion_v1\\harness\\data\\scene_events.175.sqlite3" ^
        --out-dir "C:\\VNR\\DEV\\NAIA-Event-Map-Build\\policy"

    예) Full 판(어휘 전부 · 정책 없음 · 거르개 없음)
      python tools/build_event_map_index.py ^
        --source "C:\\VNR\\DEV\\NAIA-TagSearch-Full-20260912\\tag_corpus.full.175.sqlite3" ^
        --out-dir "C:\\VNR\\DEV\\NAIA-Event-Map-Build\\full" ^
        --policy none --guard none --age-floor off

    - 관측 DB 는 2분, Full 코퍼스는 10분 안팎 걸린다. 메모리는 각각 2GB / 5GB 남짓.
    - 출력은 **파일 하나**: `<out-dir>\\event_map.naiamap` (형식은 core/event_map/pack.py).
    - 이미 결과가 있으면 쓰지 않는다(덮어쓰지 않는다). 새 폴더를 주거나 지우고 다시 돌려라.
    - 중간에 끊겨도 `*.part` 만 남고, 다음 실행이 그것을 치우고 다시 시작한다. `.part` 는 머리의
      목차가 비어 있어 색인으로 잘못 열리지도 않는다.
    - 끝나면 스스로 검증하고, 시험대를 띄우는 명령을 알려 준다.
    - 큰 빌드 전에 `--limit-rows 200000` 으로 한 번 재 보라. 1분이면 끝나고 같은 길을 다 밟는다.

원본 두 가지 (`tools/event_map_sources.py` 가 스키마를 보고 고른다)
    scene-observed-175-v1   관측 DB. **이미 걸러진 것**이다 - 행 거르개로 361,480건이 빠졌고
                            태그 100,537개 중 14,559개만 후보다. `--guard` 를 쓸 수 없다.
    tag-corpus-full-175-v1  Full 코퍼스. 원본 Parquet 175개의 물리 행 전부(9,127,788),
                            거르개도 분류도 없다. 분류·인원 그룹·행 거르개를 빌드 때 다시 계산한다.

스위치 셋
`--policy`
    full (기본) : core/event_map/policy.py 의 정책을 전부 건다.
    none        : 그 정책을 끈다 - 색상 제외(질의 시점) · 게시물 거르개 확장 · 후보 제외 갈래.
`--guard` (Full 코퍼스에만)
    source (기본) : 관측 DB 와 같은 행 거르개(연령 + 위험어 + Danger 그룹). 같은 게시물이 빠진다.
    age           : 연령 게이트만. 위험어·Danger 게시물을 되살린다.
    none          : 행 거르개를 안 건다.
`--age-floor`
    on (기본) : Q/E 게시물의 `aged down` 을 버린다.
    off       : 버리지 않는다. ⚠️ 2026-09-12 테스터 이의로 열었다 - 사유는 core/event_map/policy.py
                의 AGE_FLOOR_RE 주석. **원본 거르개의 연령 어휘와는 별개다**(그쪽은 `--guard`).

원본은 읽기 전용으로만 연다. 사용자 데이터는 건드리지 않는다.

무엇을 담나
  일반 갈래     : 원본이 후보로 둔 태그(preset_eligible) 14,559개.
  성인 갈래     : 원본이 `outside_general_prompt_projection` 으로 **빼 두기만 한** 태그 1,751개.
                 E/Q 게시물은 받아 두고 그 게시물을 E/Q 로 만드는 태그의 목록을 안 만들어서,
                 E 로 걸러도 행위 태그가 한 번도 안 나왔다(실측: E 게시물 태그의 30.9% 가 후보 밖).
  나머지 갈래   : Full 코퍼스로 지을 때만 열린다 - unclassified 82,833 · nonvisual 978 ·
                 guarded 416. 관측 DB 는 이 태그들의 목록을 아예 만들지 않았다.
  게시물 거르개 : 무엇을 몇 건 막았는지 태그·등급별로 meta["guard"]["by_tag"] 에 남긴다.
  색상 정책은 빌드가 아니라 **질의 시점**에 건다(meta["color_policy"]).
  태그 설명(영문 정의 등)은 담지 않는다 - 맵이 쓰지 않는데 31MB 였다.

부호화
  body     : 정렬된 날 정수를 한 줄로 이어 붙이고 게시물별 시작 위치(offsets)를 따로 둔다.
             어휘가 65,535개 이하면 uint16, 넘으면 uint32 다(meta["record_encoding"]).
             압축하지 않는다 - 흩어진 교집합을 읽을 때 블록을 통째로 풀어야 해서 질의마다
             0.7초가 붙는다(실측). SQLite 에도 넣지 않는다 - 흩어진 12만 행을 꺼내는 데
             810ms 가 들었다(B-tree 왕복). mmap 이면 수십 ms.
  postings : 태그별로 게시물 목록을 **합쳐서** 차분+varint+zlib. 원본은 분면마다 쪼개져
             있어 번호 간격이 벌어져 압축이 안 먹었다. 태그마다 한 번 풀고 캐시에 남는다.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
import zlib
from array import array
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from core.event_map.pack import PackWriter  # noqa: E402
from core.event_map.policy import (  # noqa: E402  (빌드와 질의가 같은 정책을 쓴다)
    POLICY_ADULT_VERSION, POLICY_MODES, POLICY_VERSION, adult_post_block, adult_role,
    post_block_rule)
from tools.event_map_sources import GUARD_HELP, GUARD_LEVELS, open_source  # noqa: E402

PACK_NAME = "event_map.naiamap"
SCHEMA = "naia-event-map-v1"

# 관측 DB 가 후보에서 뺐던 태그들의 갈래 이름. Full 코퍼스로 지을 때만 쓴다.
LANE_BY_REASON = {
    "unknown_source_classification": "unclassified",
    "nonvisual_metadata": "nonvisual",
    "nonvisual_or_unreviewed_composition": "nonvisual",
    "source_row_guard": "guarded",
}


def say(text: str) -> None:
    print(text, flush=True)


def varint(vals, out: bytearray) -> None:
    for v in vals:
        while v >= 0x80:
            out.append((v & 0x7F) | 0x80)
            v >>= 7
        out.append(v)


def encode_sorted(ids) -> bytes:
    """정렬된 id 목록 -> 개수 + 차분 varint."""
    out = bytearray()
    prev = -1
    d = []
    for i in ids:
        d.append(i - prev - 1)
        prev = i
    varint([len(d)], out)
    varint(d, out)
    return bytes(out)


def build(src_path: Path, out_file: Path, mode: str, *, guard: str = "source",
          age_floor: bool = True, limit_rows: int = 0) -> dict:
    part = out_file.with_name(out_file.name + ".part")
    if part.exists():
        say("지난 실행이 남긴 %s 를 치운다" % part.name)
        part.unlink()

    t0 = time.perf_counter()
    src = open_source(src_path, guard=guard, limit_rows=limit_rows)
    names, details = src.names, src.details
    parts = list(src.partitions)
    adult_pids = {i for i, n in enumerate(parts) if n[:1] in ("q", "e")}
    total_src = src.total

    # 1) 어휘와 갈래
    lane: dict[int, str] = {}
    role: dict[int, str] = {}
    block_all: set[int] = set()
    block_adult: set[int] = set()
    rule_of: dict[int, str] = {}
    for tid, name in names.items():
        info = details[tid]
        sub = info.get("original_subgroup")
        # (a) 행 거르개. 관측 DB 는 빌드 때 이미 뺐으므로 비어 있고, Full 코퍼스면 여기서 뺀다.
        src_rule = src.source_block.get(tid)
        if src_rule:
            block_all.add(tid)
            rule_of[tid] = src_rule
        # (b) 정책 거르개(policy.py). 같은 태그에 둘 다 걸리면 넓은 쪽(행 거르개)을 적어 둔다.
        scope = adult_post_block(name, sub, mode, age_floor)
        if scope:
            rule_of.setdefault(tid, post_block_rule(name, sub, mode, age_floor))
            (block_all if scope == "all" else block_adult).add(tid)
        # 전 등급에서 막은 태그는 후보가 아니다 - 목록이 빌 수밖에 없다.
        if tid in block_all:
            continue
        if info.get("preset_eligible"):
            lane[tid], role[tid] = "general", info.get("role") or "unreviewed"
        elif info.get("reason") == "outside_general_prompt_projection":
            r = adult_role(name, sub, mode, age_floor)
            if r:
                lane[tid], role[tid] = "adult", r
        elif src.kind == "full":
            # 관측 DB 가 후보에서 뺀 나머지. Full 코퍼스로만 열린다.
            lane[tid] = LANE_BY_REASON.get(info.get("reason"), "extended")
            role[tid] = info.get("role") or "unreviewed"
    lane_counts: dict[str, int] = {}
    for v in lane.values():
        lane_counts[v] = lane_counts.get(v, 0) + 1
    say("[1/4] 정책 %s · 거르개 %s · 연령 하한 %s" % (mode, guard, "on" if age_floor else "off"))
    say("      어휘 %s = %s"
        % (format(len(lane), ","),
           " + ".join("%s %s" % (k, format(v, ","))
                      for k, v in sorted(lane_counts.items(), key=lambda kv: -kv[1]))))
    say("      게시물 거르개 태그 %d(전 등급) + %d(Q/E)" % (len(block_all), len(block_adult)))

    # 빈도 내림차순 = 새 id. 순서는 조밀도·읽기 편함에만 쓰이고 관측 수는 아래에서 다시 센다.
    order = sorted(lane, key=lambda t: (-(details[t].get("admitted_posts") or 0), names[t]))
    # 어휘가 uint16 을 넘으면 본문을 uint32 로 쓴다(리더가 meta 를 보고 맞춘다).
    width = 2 if len(order) <= 65535 else 4
    typecode = "H" if width == 2 else "I"
    if len(order) >= 2 ** 32:
        raise SystemExit("어휘가 uint32 를 넘는다(%d)" % len(order))
    newid = {old: k for k, old in enumerate(order)}
    postings = [array("I") for _ in order]

    pw = PackWriter(part)

    # 2) 게시물 본문. postings 도 여기서 만든다 - 원본 postings 를 베끼면 새로 막은 게시물이
    #    목록에 남는다.
    say("[2/4] 게시물 %s건을 훑는다... (태그당 %d바이트)" % (format(total_src, ","), width))
    t1 = time.perf_counter()
    part_bytes = bytearray()
    # ⚠️ rid 로 색인한다(분면표와 같은 규칙). rid 는 1부터라 0번 자리는 비어 있고,
    #    막은 게시물은 길이 0 짜리로 자리만 남긴다.
    offsets = array("I", [0])
    little = sys.byteorder == "little"
    kept = 0
    dropped = {"all": 0, "adult": 0}
    # 막은 게시물을 태그·규칙별로 센다. 한 게시물이 여러 태그·규칙에 걸리면 **각각에** 센다
    # (합은 실제 버린 수보다 크다 - 실제 수는 dropped).
    by_tag: dict[str, dict[str, int]] = {}     # 막은 태그 -> 등급 -> 게시물 수
    by_rule: dict[str, dict[str, int]] = {}    # 규칙 -> 등급 -> 게시물 수
    blocked_sample: list[int] = []
    cursor = 0
    next_report = 1_000_000
    chunks: list[bytes] = []
    last_rid = 0
    pw.begin("body")
    for rid, pid, tags in src.rows():
        last_rid = rid
        hit_all = tags & block_all
        hit_adult = (tags & block_adult) if pid in adult_pids else set()
        if hit_all or hit_adult:
            dropped["all" if hit_all else "adult"] += 1
            # ⚠️ 걸린 규칙 **전부**에 센다. 앞 규칙에서 멈추면 `selfcest` + `aged down` 게시물이
            #    연령 하한 쪽에 안 잡혀 보고서의 연령 하한이 1,291 이 아니라 1,279 로 나왔다.
            hit = hit_all | hit_adult
            rating = parts[pid][:1]
            for t in hit:
                row = by_tag.setdefault(names[t], {})
                row[rating] = row.get(rating, 0) + 1
            for rule in {rule_of[t] for t in hit}:
                row = by_rule.setdefault(rule, {})
                row[rating] = row.get(rating, 0) + 1
            if len(blocked_sample) < 300:
                blocked_sample.append(rid)
            ids = []
        else:
            ids = sorted(newid[t] for t in tags if t in newid)
        packed = array(typecode, ids)
        if not little:
            packed.byteswap()    # 파일은 항상 little-endian
        chunks.append(packed.tobytes())
        while len(offsets) <= rid:
            offsets.append(cursor)
        cursor += len(packed)
        offsets.append(cursor)   # offsets[rid+1] = 끝
        while len(part_bytes) < rid:
            part_bytes.append(0)
        part_bytes.append(pid)
        if ids:
            kept += 1
            for k in ids:
                postings[k].append(rid)
        if len(chunks) >= 100_000:
            pw.write(b"".join(chunks))
            chunks.clear()
        if rid >= next_report:
            el = time.perf_counter() - t1
            say("      %5.1f%%  %s건  %.0f초 경과, 약 %.0f초 남음"
                % (100 * rid / total_src, format(rid, ","), el, el * (total_src - rid) / rid))
            next_report += 1_000_000
    if chunks:
        pw.write(b"".join(chunks))
    pw.end()
    src.close()
    # 분면표도 rid 로 색인하므로 오프셋 표와 같은 길이로 맞춘다(마지막 rid + 1).
    while len(part_bytes) < len(offsets) - 1:
        part_bytes.append(0)
    if not little:
        offsets.byteswap()
    pw.add("offsets", offsets.tobytes())
    pw.add("partitions", bytes(part_bytes))
    say("      남긴 게시물 %s  /  버린 게시물 %s(전 등급) + %s(Q/E)  /  본문 %.0f MB  (%.0f초)"
        % (format(kept, ","), format(dropped["all"], ","), format(dropped["adult"], ","),
           cursor * width / 1048576, time.perf_counter() - t1))

    # 3) 태그별 게시물 목록 + 태그표. 관측 수는 거르개 **뒤**의 실제 목록 길이다.
    say("[3/4] 태그별 게시물 목록을 싼다...")
    t2 = time.perf_counter()
    post_index = array("Q", [0])
    tag_rows = []
    entries = 0
    pw.begin("postings")
    for old in order:
        k = newid[old]
        blob = zlib.compress(encode_sorted(postings[k]), 6)   # rid 순으로 쌓였다
        pw.write(blob)
        post_index.append(post_index[-1] + len(blob))
        tag_rows.append([names[old], len(postings[k]), role[old], lane[old]])
        entries += len(postings[k])
        postings[k] = None
    pw.end()
    if entries != cursor:
        raise SystemExit("본문(%d)과 목록(%d)의 엔트리 수가 다르다 - 빌드가 어긋났다" % (cursor, entries))
    if not little:
        post_index.byteswap()
    pw.add("post_index", post_index.tobytes())
    pw.add_json("tags", tag_rows)
    pw.add_json("meta", {
        "schema": SCHEMA,
        "state": "ready",
        "record_encoding": "uint%d-le-flat" % (width * 8),
        "record_width": width,
        "records": kept,
        "rows_scanned": last_rid,
        "tags": len(order),
        "lanes": lane_counts,
        "partitions": parts,
        "policy_mode": mode,
        "row_guard": guard,
        "age_floor": "on" if age_floor else "off",
        "color_policy": "on" if mode == "full" else "off",
        "policy": ([POLICY_VERSION, POLICY_ADULT_VERSION] if mode == "full" else ["none"])
                  + (["age-floor"] if age_floor else []),
        "guard": {"dropped_all_ratings": dropped["all"], "dropped_adult_ratings": dropped["adult"],
                  "block_tags_all": len(block_all), "block_tags_adult": len(block_adult),
                  "row_guard_level": "%s - %s" % (guard, GUARD_HELP[guard]),
                  "by_rule": by_rule, "by_tag": by_tag},
        "source": src.source_meta,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "limit_rows": limit_rows or None,
        "note": "관측 수는 같은 게시물에 함께 달린 횟수다. 의도의 정확도가 아니다.",
    })
    pw.close()          # 여기서 머리의 목차가 채워진다
    say("      %.0f초" % (time.perf_counter() - t2))

    # 목차까지 다 쓴 뒤에야 제 이름을 준다 - 끊기면 *.part 만 남는다.
    os.replace(part, out_file)
    return {"kept": kept, "dropped": dropped, "blocked_sample": blocked_sample,
            "seconds": time.perf_counter() - t0}


def self_check(index_path: Path, blocked_sample: list[int]) -> None:
    """만든 색인을 실제 리더로 열어 앞뒤가 맞는지 본다."""
    import numpy as np
    from core.event_map import EventMapIndex

    say("[4/4] 검증...")
    idx = EventMapIndex(index_path)
    try:
        problems = []
        # (a) 본문의 태그마다 그 태그의 게시물 목록에 이 게시물이 있어야 한다.
        # ⚠️ 게시물별로 돌면 안 된다 - 한 게시물의 태그 30여 개를 차례로 물으면 `1girl` 같은
        #    큰 목록이 캐시(512칸) 밖으로 밀려 매번 다시 풀린다. 어휘 10만짜리 Full 판에서
        #    이 루프만 8분을 먹었다. **태그별로 묶어** 태그마다 한 번만 푼다.
        rng = random.Random(0)
        live = sorted({r for r in (rng.randrange(1, len(idx.offsets) - 1) for _ in range(4000))
                       if idx.offsets[r + 1] > idx.offsets[r]})[:2000]
        want: dict[int, list[int]] = {}
        for rid in live:
            for tid in idx.body[idx.offsets[rid]:idx.offsets[rid + 1]].tolist():
                want.setdefault(int(tid), []).append(rid)
        for tid, rids in want.items():
            post = idx.posting(tid)
            found = np.searchsorted(post, rids)
            bad = [r for r, i in zip(rids, found.tolist())
                   if i >= post.size or int(post[i]) != r]
            if bad:
                problems.append("태그 %s 의 목록에 게시물 %s 가 없다" % (idx.by_id[tid], bad[0]))
        # (b) 막은 게시물은 비어 있어야 한다
        for rid in blocked_sample:
            if idx.offsets[rid + 1] != idx.offsets[rid]:
                problems.append("막은 게시물 rid %d 에 본문이 남았다" % rid)
        # (c) 관측 수 == 목록 길이
        for tid in rng.sample(sorted(idx.by_id), min(300, len(idx.by_id))):
            if idx.posting(tid).size != idx.observed[tid]:
                problems.append("태그 %s 의 관측 수와 목록 길이가 다르다" % idx.by_id[tid])
        if problems:
            for p in problems[:10]:
                say("      실패: " + p)
            raise SystemExit("검증 실패 %d건 - 이 색인을 쓰지 마라" % len(problems))
        say("      게시물 %d건(태그 %d종) · 막은 게시물 %d건 · 태그 %d개 대조 - 전부 맞다"
            % (len(live), len(want), len(blocked_sample), min(300, len(idx.by_id))))

        r = idx.explore(["armpits", "armpit crease"], limit=3)
        say("      시험 질의 armpits + armpit crease -> %s건 (%s ms): %s"
            % (format(r["observed_posts"], ","), r.get("elapsed_ms"),
               ", ".join(c["tag"] for c in r["candidates"])))
        r = idx.explore(["kiss"], ratings=["e"], limit=5)
        say("      시험 질의 kiss (E)             -> %s건: %s"
            % (format(r["observed_posts"], ","), ", ".join(c["tag"] for c in r["candidates"])))
    finally:
        idx.close()


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")     # cp949 콘솔에서도 죽지 않게
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description="이벤트 맵 색인을 만든다 (자세한 설명은 파일 머리 주석)",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True,
                    help="원본 DB (관측 DB 또는 Full 코퍼스) - 읽기만 한다")
    ap.add_argument("--out-dir", required=True,
                    help="결과(event_map.naiamap)를 쓸 폴더. 없으면 만든다. 이미 결과가 있으면 거부한다")
    ap.add_argument("--policy", choices=POLICY_MODES, default="full",
                    help="full=정책 전부(기본) / none=정책 끔")
    ap.add_argument("--guard", choices=GUARD_LEVELS, default="source",
                    help=" / ".join("%s=%s" % (k, GUARD_HELP[k]) for k in GUARD_LEVELS))
    ap.add_argument("--age-floor", choices=("on", "off"), default="on",
                    help="on=Q/E 의 `aged down` 게시물을 버린다(기본) / off=버리지 않는다")
    ap.add_argument("--limit-rows", type=int, default=0,
                    help="앞 N행만 읽는다(시험용). 0=전부")
    args = ap.parse_args()

    src_path = Path(args.source).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_file = out_dir / PACK_NAME
    if not src_path.is_file():
        raise SystemExit("원본이 없다: %s" % src_path)
    if out_file.exists():
        raise SystemExit("이미 결과가 있다. 덮어쓰지 않는다: %s\n"
                         "  새 폴더를 --out-dir 로 주거나, 그 파일을 지우고 다시 돌려라." % out_file)
    out_dir.mkdir(parents=True, exist_ok=True)

    say("원본 : %s" % src_path)
    say("출력 : %s" % out_file)
    say("설정 : 정책 %s · 거르개 %s · 연령 하한 %s%s"
        % (args.policy, args.guard, args.age_floor,
           " · 앞 %s행만" % format(args.limit_rows, ",") if args.limit_rows else ""))
    result = build(src_path, out_file, args.policy, guard=args.guard,
                   age_floor=args.age_floor == "on", limit_rows=args.limit_rows)
    self_check(out_file, result["blocked_sample"])

    say("")
    say("완료 (%.0f초)  %s  %.1f MB"
        % (result["seconds"], out_file, out_file.stat().st_size / 1048576))
    say("")
    say("시험대 띄우기:")
    say('  python "%s" --index "%s"' % (REPO / "tools" / "event_map_playground.py", out_file))


if __name__ == "__main__":
    main()
