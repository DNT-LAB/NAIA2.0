"""E621 태그의 인원 분포 표를 굽는다 → data/e621_count_profile.parquet (읽는 쪽 = core/e621_count_profile.py).

게시물 스냅숏(e621_events.e621map · 1.15GB)을 두 번 훑는다 - 게시물마다 인원 태그(solo · duo · trio · group)의
묶음을 적고, 태그마다 그 묶음별 게시물 수를 센다. 관계 팩과 같은 스냅숏이어야 한다(해시로 대조한다).

    python tools/build_e621_count_profile.py --source codex_out/e621-foundation-v1/data

약 10초. 표에는 센 수만 담는다 - 인원 태그를 붙이는 기준은 core/e621_count_profile.py 에 있다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STEP = 200_000   # 한 번에 보는 게시물 수 - 임시 배열을 수십 MB 로 묶는다


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def build(args) -> dict:
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq
    from core.e621_count_profile import COUNT_TAGS, METADATA_KEY, SCHEMA, pick_count_tag
    from core.e621_relation_repository import E621RelationRepository
    from core.event_map.pack import PackReader
    from core.site_tag_repository import collect_legacy_tags

    started = time.perf_counter()
    source = args.source / "e621_events.e621map"
    product = {row["tag"] for row in collect_legacy_tags(json.loads(args.vocabulary.read_bytes()))}
    reader = PackReader(source)
    meta = reader.json_of("meta")
    if meta.get("schema") != "naia.e621-observations.v1" or meta.get("site") != "e621":
        reader.close()
        raise ValueError("expected the site-separated E621 observations schema")
    names = [name for name, _ in reader.json_of("tags")]
    raw = {name: index for index, name in enumerate(names)}
    missing = [tag for tag in COUNT_TAGS if tag not in raw]
    if missing:
        raise ValueError(f"count tags missing from the snapshot: {missing}")

    def view(section, dtype):
        start, length = reader.span(section)
        return np.frombuffer(reader.map, dtype=dtype, count=length // np.dtype(dtype).itemsize, offset=start)

    body, offsets, ratings = view("body", "<u4"), view("offsets", "<u8"), view("ratings", "u1")
    posts = len(ratings)
    bit_of = np.zeros(len(names), dtype=np.uint8)
    for bit, tag in enumerate(COUNT_TAGS):
        bit_of[raw[tag]] = 1 << bit

    # 1) 게시물마다 인원 태그의 비트 묶음
    flags = np.zeros(posts, dtype=np.uint8)
    for lo in range(0, posts, STEP):
        hi = min(lo + STEP, posts)
        bits = bit_of[body[int(offsets[lo]):int(offsets[hi])]]
        hit = np.nonzero(bits)[0]
        if len(hit):
            owner = np.repeat(np.arange(lo, hi, dtype=np.int64), np.diff(offsets[lo:hi + 1]).astype(np.int64))[hit]
            np.bitwise_or.at(flags, owner, bits[hit])

    # 2) 태그 × 비트 묶음(16가지) 표
    width = 1 << len(COUNT_TAGS)
    table = np.zeros(len(names) * width, dtype=np.int64)
    for lo in range(0, posts, STEP):
        hi = min(lo + STEP, posts)
        ids = body[int(offsets[lo]):int(offsets[hi])].astype(np.int64)
        per = np.repeat(flags[lo:hi], np.diff(offsets[lo:hi + 1]).astype(np.int64)).astype(np.int64)
        table += np.bincount(ids * width + per, minlength=len(table))
    table = table.reshape(-1, width)
    total = table.sum(axis=1)
    with_tag = {tag: table[:, [combo for combo in range(width) if combo >> bit & 1]].sum(axis=1)
                for bit, tag in enumerate(COUNT_TAGS)}

    rows = sorted((name, int(total[index]), *(int(with_tag[tag][index]) for tag in COUNT_TAGS))
                  for index, name in enumerate(names) if name in product and total[index] >= args.min_support)
    source_sha = sha256(source)

    # 관계 팩은 같은 스냅숏을 따로 센 것이다 - 태그별 게시물 수가 한 건도 어긋나면 안 된다.
    pack = E621RelationRepository(ROOT)
    checked = 0
    if pack.load():
        pack_sha = pack._meta.get("sources", {}).get("observations", {}).get("sha256")
        if pack_sha != source_sha:
            raise ValueError("the relation pack was built from a different snapshot")
        for name, tag_total, *_ in rows:
            tag_id = pack._ids.get(name)
            if tag_id is None:
                continue
            if sum(pack._counts[tag_id * 3:tag_id * 3 + 3]) != tag_total:
                raise ValueError(f"post count disagrees with the relation pack: {name}")
            checked += 1

    profile_meta = {
        "schema": SCHEMA, "site": "e621", "snapshot": args.snapshot, "posts": posts, "min_support": args.min_support,
        "count_tags": list(COUNT_TAGS), "rows": len(rows),
        "source": {"file": source.name, "sha256": source_sha},
        "note": "counts only; the rule that picks a count tag lives in core/e621_count_profile.py",
    }
    columns = list(zip(*rows)) if rows else [[], [], [], [], [], []]
    arrow = pa.table({"tag": pa.array(columns[0], pa.string()),
                      **{name: pa.array(columns[index + 1], pa.int32())
                         for index, name in enumerate(("total", *COUNT_TAGS))}})
    arrow = arrow.replace_schema_metadata({METADATA_KEY: json.dumps(profile_meta, ensure_ascii=False).encode("utf-8")})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(arrow, args.output, compression="zstd")

    picked = {}
    for name, *counts in rows:
        kind = "" if name in COUNT_TAGS else pick_count_tag(*counts)
        picked[kind] = picked.get(kind, 0) + 1
    report = {**profile_meta, "bytes": args.output.stat().st_size, "sha256": sha256(args.output),
              "checked_against_relation_pack": checked, "picked": picked,
              "build_seconds": round(time.perf_counter() - started, 1)}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    # mmap 을 보는 배열을 놓은 뒤에 닫는다.
    del body, offsets, ratings
    reader.close()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="e621_events.e621map 이 든 폴더")
    parser.add_argument("--vocabulary", type=Path, default=ROOT / "data/e621_data")
    parser.add_argument("--output", type=Path, default=ROOT / "data/e621_count_profile.parquet")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--snapshot", default="2025-07-26")
    parser.add_argument("--min-support", type=int, default=100)
    build(parser.parse_args())
