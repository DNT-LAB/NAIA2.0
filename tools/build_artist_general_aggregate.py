"""general 축 **집계표**를 굽는다 — `data/artist_tag_general.naiapack`.

    python tools/build_artist_general_aggregate.py \
        --corpus C:/VNR/DEV/NAIA-TagSearch-Full-20260912/tag_corpus.full.175.sqlite3 \
        --tags   C:/VNR/DEV/NAIA2.0/NAIA-Portable/user-data/data/tags

무엇을 담나
    general 태그마다 **(작가, 그 태그를 그린 횟수)** 쌍을, 횟수가 `--min-count`
    (기본 10) 이상인 것만. 역색인(postings)은 담지 않는다.

왜 집계인가 (사용자 결정 2026-09-19, 방안 B)
    깊이 검색이 general 축에 묻는 것은 `count(작가, 태그) >= 문턱` 하나뿐이다.
    그 답만 담으면 **약 12MB** 로 끝난다 - postings 를 통째로 담으면 528MB
    (압축 후에도 +256MB)라 배포판이 배로 커진다.

    대가는 하나다: **문턱 아래는 못 센다.** `--min-count` 밑으로는 자료가 없다.
    읽는 쪽이 그 문턱을 `meta.min_count` 로 알고 화면에 알린다.

⚠️ 이 파일에 박혀 있는 규칙 넷
  * **작가 코드는 친화도 팩에서 그대로 가져온다.** 다시 만들지 않는다 - parquet 에서
    다시 세면 정렬 하나만 달라도 작가가 통째로 어긋나고 **건수는 그럴듯하다**.
    그래서 `--affinity` 가 필수 입력이고, 이 표는 그 팩과 **짝으로만** 쓸 수 있다.
  * **코퍼스가 같은 빌드여야 한다.** 친화도 팩의 `meta.source.sha256` 과 코퍼스의
    `source_manifest_sha256` 이 다르면 굽기를 거절한다. 행 번호가 그 빌드 하나에
    못 박혀 있기 때문이다.
  * **1-based -> 0-based.** 원본 sqlite 의 행 번호는 1부터다. 친화도 팩의
    `rid_artist` 는 0-based 배열이다(`meta.rid_base`). 한 번 빼는 이 줄이 전부다.
  * **한 작가도 문턱을 못 넘는 태그는 어휘에서 뺀다.** 남겨 두면 사용자가 고를 수
    있는데 결과가 늘 0건이다 - "이 색인에 없다" 가 정직하다. 뺀 수는 meta 에 적는다.

산출물은 스스로를 검산한다. `--tags` 를 주면 parquet 전수 주사와 맞대고(권장),
안 주면 구운 팩을 다시 열어 굽기 전 집계와 맞대는 것까지만 한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
import zlib
from array import array
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
# 이 저장소의 콘솔은 cp949 다 - 한글 진행 표시가 깨지지 않게 먼저 돌려 둔다.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.event_map.index import decode_postings  # noqa: E402
from core.event_map.pack import PackReader, PackWriter  # noqa: E402

SCHEMA = "naia-artist-general-v1"
FIELD = "general"
REQUIRED_SECTIONS = (
    "meta", "names_general", "posts_general",
    "id_index", "ids_general", "cnt_index", "counts_general",
)
# 검산 표본. 흔한 것과 드문 것을 섞는다 - 흔한 것만 보면 꼬리에서 나는 오류를 놓친다.
VERIFY_TAGS = ("1girl", "small breasts", "twintails", "ovipositor", "maid")


def jzlib(obj) -> bytes:
    return zlib.compress(json.dumps(obj, ensure_ascii=False).encode("utf-8"), 6)


_VARINT_WIDTH = ((1 << 7, 2), (1 << 14, 3), (1 << 21, 4), (1 << 28, 5))


def varints(values: np.ndarray) -> np.ndarray:
    """LEB128. 한 바이트씩 파이썬으로 돌면 수백만 값에 몇 분이 든다."""
    width = np.ones(values.size, dtype=np.int64)
    for limit, size in _VARINT_WIDTH:
        width[values >= limit] = size
    offset = np.zeros(values.size, dtype=np.int64)
    np.cumsum(width[:-1], out=offset[1:])
    out = np.zeros(int(width.sum()), dtype=np.uint8)
    for i in range(5):
        keep = width > i
        if not keep.any():
            break
        chunk = ((values[keep] >> (7 * i)) & 0x7F).astype(np.uint8)
        more = (width[keep] > i + 1).astype(np.uint8) << 7
        out[offset[keep] + i] = chunk | more
    return out


def encode_postings(rids: np.ndarray) -> bytes:
    """`.naiamap`·친화도 팩과 같은 인코딩: zlib(개수 + (간격-1) varint)."""
    deltas = np.diff(np.concatenate(([-1], rids))) - 1
    body = np.concatenate([varints(np.array([rids.size])), varints(deltas)])
    return zlib.compress(body.tobytes(), 6)


# ------------------------------------------------------- 짝이 맞는 입력인가
def load_affinity(path: Path) -> dict:
    """친화도 팩에서 **작가 코드와 이름표를 그대로** 가져온다.

    다시 만들지 않는 이유는 머리말에 적었다 - 어긋나도 숫자는 그럴듯하다.
    """
    if not path.is_file():
        raise SystemExit(
            f"친화도 팩이 없다: {path}\n"
            "  먼저 tools/build_artist_affinity_pack.py 로 구울 것 "
            "(이 표는 그 팩의 작가 색인을 그대로 쓴다).")
    reader = PackReader(path)
    try:
        meta = reader.json_of("meta")
        codes = np.frombuffer(zlib.decompress(reader.bytes_of("rid_artist")),
                              dtype=np.uint32)
        artists = json.loads(zlib.decompress(reader.bytes_of("artist_names")))
    finally:
        reader.close()
    if int(meta.get("rid_base", -1)) != 0:
        raise SystemExit("친화도 팩의 rid_base 가 0 이 아니다 - 자리 옮김 규칙이 다르다")
    return {"meta": meta, "codes": codes, "artists": artists,
            "sha256": ((meta.get("source") or {}).get("sha256") or "")}


def check_same_corpus(db: sqlite3.Connection, affinity: dict) -> str:
    """두 입력이 **같은 코퍼스 빌드**에서 나왔는가.

    행 번호는 코퍼스 빌드 하나에 못 박혀 있다. 여기서 안 막으면 엉뚱한 작가가
    붙은 표가 조용히 만들어진다 - 건수가 그럴듯해서 아무도 못 본다.
    """
    row = db.execute(
        "SELECT value FROM metadata WHERE key='source_manifest_sha256'").fetchone()
    raw = str(row[0]).strip() if row and row[0] else ""
    try:
        sha = json.loads(raw) if raw.startswith('"') else raw
    except json.JSONDecodeError:
        sha = raw.strip('"')
    want = str(affinity["sha256"] or "")
    if not sha or not want:
        raise SystemExit("코퍼스나 친화도 팩에 source sha256 이 없다 - 짝을 확인할 수 없다")
    if sha.lower() != want.lower():
        raise SystemExit(
            "코퍼스와 친화도 팩이 **다른 빌드**다 - 행 번호를 믿을 수 없다.\n"
            f"  코퍼스    {sha}\n  친화도 팩 {want}\n"
            "  같은 코퍼스로 구운 친화도 팩을 --affinity 로 줄 것.")
    rows = int(db.execute("SELECT COUNT(*) FROM records").fetchone()[0])
    if rows != int(affinity["meta"].get("rows", -1)):
        raise SystemExit(f"코퍼스 records {rows:,} != 친화도 팩 rows "
                         f"{affinity['meta'].get('rows'):,}")
    print(f"[정합] 같은 코퍼스 빌드 (sha {sha[:12]}...) · 행 {rows:,} · "
          f"작가 {len(affinity['artists'])-1:,}명")
    return sha


# ------------------------------------------------------------------- 굽기
def build_aggregate(db: sqlite3.Connection, codes: np.ndarray, n_artists: int,
                    min_count: int, rows: int) -> dict:
    """general 태그마다 (작가, 횟수) 쌍을 문턱 이상만 남긴다."""
    started = time.monotonic()
    cur = db.execute(
        "SELECT t.name, p.data, p.cardinality FROM tags t JOIN postings p "
        "ON p.tag=t.id WHERE t.field=? ORDER BY t.id", (FIELD,))
    names: list[str] = []
    posts: list[int] = []
    id_chunks: list[bytes] = []
    cnt_chunks: list[bytes] = []
    id_off, cnt_off = [0], [0]
    seen = dropped = pairs = incidences = 0
    for name, blob, cardinality in cur:
        seen += 1
        raw = array('I')
        raw.frombytes(zlib.decompress(blob))
        rids = np.frombuffer(raw, dtype=np.uint32).astype(np.int64)
        if rids.size != cardinality:
            raise SystemExit(f"{FIELD}/{name}: postings 개수가 안 맞는다")
        if rids.size and (rids.min() < 1 or rids.max() > rows):
            raise SystemExit(f"{FIELD}/{name}: 행 번호가 범위 밖이다 "
                             f"({rids.min()}..{rids.max()}, rows={rows})")
        incidences += int(rids.size)
        # 1-based -> 0-based. 이 한 줄이 이 표의 유일한 자리 옮김이다.
        picked = codes[rids - 1]
        # ⚠️ 0 은 '작가 없음/합작' 이다. 빼지 않으면 한 사람으로 뭉쳐 늘 1등이 된다.
        picked = picked[picked != 0]
        ids, counts = np.unique(picked, return_counts=True)
        keep = counts >= min_count
        ids, counts = ids[keep], counts[keep]
        if ids.size == 0:
            # 아무도 문턱을 못 넘는다 - 어휘에서 뺀다(고를 수는 있는데 늘 0건이면 더 나쁘다).
            dropped += 1
            continue
        names.append(str(name))
        posts.append(int(cardinality))
        ids64 = ids.astype(np.int64)
        id_blob = encode_postings(ids64)
        cnt_blob = zlib.compress(counts.astype(np.uint32).tobytes(), 6)
        id_chunks.append(id_blob)
        cnt_chunks.append(cnt_blob)
        id_off.append(id_off[-1] + len(id_blob))
        cnt_off.append(cnt_off[-1] + len(cnt_blob))
        pairs += int(ids.size)
        if seen % 20000 == 0:
            print(f"    ... {seen:,} 태그 · 쌍 {pairs:,} "
                  f"({time.monotonic()-started:.0f}s)")
    ids_body = b"".join(id_chunks)
    cnt_body = b"".join(cnt_chunks)
    print(f"[{FIELD:>9}] {time.monotonic()-started:.0f}s 태그 {seen:,} "
          f"-> 남김 {len(names):,} (문턱 미달로 뺀 것 {dropped:,}) · "
          f"건수 {incidences:,} · 쌍 {pairs:,} · "
          f"ids {len(ids_body)/1024**2:.1f}MB + counts {len(cnt_body)/1024**2:.1f}MB")
    return {
        "names": names,
        "posts": np.asarray(posts, dtype=np.uint32),
        "id_index": np.asarray(id_off, dtype=np.uint64),
        "ids": ids_body,
        "cnt_index": np.asarray(cnt_off, dtype=np.uint64),
        "counts": cnt_body,
        "stats": {"tags_seen": seen, "tags_kept": len(names), "tags_dropped": dropped,
                  "pairs": pairs, "incidences": incidences,
                  "ids_bytes": len(ids_body), "counts_bytes": len(cnt_body)},
    }


def write_pack(out: Path, *, meta: dict, built: dict) -> None:
    """`*.part` 로 쓰고 다 되면 제자리에 옮긴다 - 끊긴 빌드가 표 행세를 못 하도록."""
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_suffix(out.suffix + ".part")
    part.unlink(missing_ok=True)
    writer = PackWriter(part, required=REQUIRED_SECTIONS)
    try:
        writer.add("meta", json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        writer.add("names_general", jzlib(built["names"]))
        writer.add("posts_general", built["posts"].tobytes())
        writer.add("id_index", built["id_index"].tobytes())
        writer.add("ids_general", built["ids"])
        writer.add("cnt_index", built["cnt_index"].tobytes())
        writer.add("counts_general", built["counts"])
        writer.close()
    except BaseException:
        try:
            writer.f.close()
        except Exception:
            pass
        part.unlink(missing_ok=True)
        raise
    part.replace(out)


# ------------------------------------------------------------------ 검산
def read_back(out: Path, tag: str) -> tuple[np.ndarray, np.ndarray, int] | None:
    """구운 표를 **읽는 쪽과 같은 길로** 다시 푼다."""
    reader = PackReader(out)
    try:
        names = json.loads(zlib.decompress(reader.bytes_of("names_general")))
        try:
            tid = names.index(tag)
        except ValueError:
            return None
        posts = np.frombuffer(reader.bytes_of("posts_general"), dtype=np.uint32)
        id_index = np.frombuffer(reader.bytes_of("id_index"), dtype=np.uint64)
        cnt_index = np.frombuffer(reader.bytes_of("cnt_index"), dtype=np.uint64)
        ids_base = reader.span("ids_general")[0]
        cnt_base = reader.span("counts_general")[0]
        a, b = ids_base + int(id_index[tid]), ids_base + int(id_index[tid + 1])
        ids = decode_postings(zlib.decompress(reader.map[a:b]))
        c, d = cnt_base + int(cnt_index[tid]), cnt_base + int(cnt_index[tid + 1])
        counts = np.frombuffer(zlib.decompress(reader.map[c:d]), dtype=np.uint32)
        return ids, counts, int(posts[tid])
    finally:
        reader.close()


def verify_roundtrip(out: Path, built: dict, wanted: list[str]) -> bool:
    """구운 표를 다시 열어 **굽기 전 집계와 같은지** 본다(코덱 사고를 잡는다)."""
    ok = True
    lookup = {name: i for i, name in enumerate(built["names"])}
    reader = PackReader(out)
    try:
        id_index = np.frombuffer(reader.bytes_of("id_index"), dtype=np.uint64)
        cnt_index = np.frombuffer(reader.bytes_of("cnt_index"), dtype=np.uint64)
        ids_base = reader.span("ids_general")[0]
        cnt_base = reader.span("counts_general")[0]
        for tag in wanted:
            tid = lookup.get(tag)
            if tid is None:
                print(f"[왕복] {tag}: 표에 없다(문턱 미달이거나 코퍼스에 없다)")
                continue
            a, b = ids_base + int(id_index[tid]), ids_base + int(id_index[tid + 1])
            c, d = cnt_base + int(cnt_index[tid]), cnt_base + int(cnt_index[tid + 1])
            ids = decode_postings(zlib.decompress(reader.map[a:b]))
            counts = np.frombuffer(zlib.decompress(reader.map[c:d]), dtype=np.uint32)
            same = (ids.size == counts.size
                    and bool(np.all(np.diff(ids) > 0)))
            print(f"[왕복] {tag}: 쌍 {ids.size:,} · 합 {int(counts.sum()):,} · "
                  f"{'정상' if same else '깨짐'}")
            ok &= same
    finally:
        reader.close()
    return ok


def scan_truth(tag_dir: Path, wanted: list[str], artists: list[str]) -> dict:
    """parquet 전수 주사로 낸 정답. 한 번 훑으며 태그를 모두 본다."""
    import pandas as pd
    import pyarrow as pa
    import pyarrow.compute as pc
    from importlib import util as _util

    spec = _util.spec_from_file_location(
        "build_artist_affinity_pack", REPO / "tools" / "build_artist_affinity_pack.py")
    affinity_builder = _util.module_from_spec(spec)
    spec.loader.exec_module(affinity_builder)

    started = time.monotonic()
    patterns = {tag: r'(^|,)\s*' + re.escape(tag) + r'\s*(,|$)' for tag in wanted}
    tally = {tag: Counter() for tag in wanted}
    for path in sorted(tag_dir.glob("tags_*.parquet")):
        frame = pd.read_parquet(path, columns=["artist", "general"], engine="pyarrow")
        artist = affinity_builder.resolve_artist_column(frame["artist"])
        column = pa.array(frame["general"].fillna("").astype(str), from_pandas=True)
        for tag in wanted:
            mask = pc.fill_null(pc.match_substring_regex(column, patterns[tag]),
                                False).to_numpy(zero_copy_only=False)
            hit = artist[mask]
            tally[tag].update(hit[hit != ""].tolist())
    print(f"[검산] 전수 주사 {time.monotonic()-started:.0f}s ({len(wanted)}개 태그 동시)")
    return tally


def verify_against_parquet(out: Path, tag_dir: Path, artists: list[str],
                           wanted: list[str], min_count: int) -> bool:
    truth = scan_truth(tag_dir, wanted, artists)
    ok = True
    for tag in wanted:
        got = read_back(out, tag)
        expect = Counter({k: v for k, v in truth[tag].items() if v >= min_count})
        if got is None:
            if expect:
                print(f"[검산] {tag}: 표에 없는데 전수 주사에는 "
                      f"{len(expect):,}명이 문턱을 넘는다 - 불일치")
                ok = False
            else:
                print(f"[검산] {tag}: 양쪽 다 문턱을 넘는 작가가 없다 - 일치")
            continue
        ids, counts, _posts = got
        mine = Counter({artists[int(i)]: int(c) for i, c in zip(ids, counts)})
        same = mine == expect
        ok &= same
        print(f"[검산] {tag}: 작가 {len(mine):,} · 건수 {sum(mine.values()):,} · "
              f"전수 주사와 {'일치' if same else '불일치'}")
        if not same:
            diff = [(k, mine.get(k, 0), expect.get(k, 0))
                    for k in set(mine) | set(expect)
                    if mine.get(k, 0) != expect.get(k, 0)]
            print(f"        어긋난 작가 {len(diff):,} 표본={diff[:5]}")
    return bool(ok)


# ------------------------------------------------------------------- main
def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", required=True, type=Path,
                        help="tag_corpus.full.175.sqlite3 (general 역색인 원본)")
    parser.add_argument("--affinity", type=Path,
                        default=REPO / "data" / "artist_tag_affinity.naiapack",
                        help="작가 색인을 가져올 친화도 팩(같은 코퍼스로 구운 것)")
    parser.add_argument("--tags", type=Path, default=None,
                        help="parquet 폴더. 주면 전수 주사로 교차검증한다(권장)")
    parser.add_argument("--out", type=Path,
                        default=REPO / "data" / "artist_tag_general.naiapack")
    parser.add_argument("--min-count", type=int, default=10,
                        help="이 횟수 미만인 (작가,태그) 쌍은 담지 않는다 (기본 10)")
    parser.add_argument("--force", action="store_true", help="기존 산출물을 덮어쓴다")
    args = parser.parse_args()

    if args.min_count < 1:
        raise SystemExit("--min-count 는 1 이상이어야 한다")
    if args.out.exists() and not args.force:
        raise SystemExit(f"이미 있다: {args.out}  (덮어쓰려면 --force)")
    if not args.corpus.is_file():
        raise SystemExit(f"원본 코퍼스가 없다: {args.corpus}")
    if args.tags is not None and not args.tags.is_dir():
        raise SystemExit(f"parquet 폴더가 없다: {args.tags}")

    started = time.monotonic()
    affinity = load_affinity(args.affinity)
    db = sqlite3.connect(args.corpus)
    sha = check_same_corpus(db, affinity)
    rows = int(affinity["meta"]["rows"])

    built = build_aggregate(db, affinity["codes"], len(affinity["artists"]),
                            args.min_count, rows)

    meta = {
        "schema": SCHEMA,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "axis": FIELD,
        "rows": rows,
        "artists": len(affinity["artists"]) - 1,
        "min_count": args.min_count,
        "min_count_note": (
            f"이 표에는 횟수 {args.min_count} 이상인 쌍만 있다. 그보다 낮은 문턱으로 "
            "물으면 답할 수 없다 - 읽는 쪽이 이 값으로 화면을 잡아 줘야 한다."),
        "stats": built["stats"],
        # 짝을 못 박는 두 줄. 읽는 쪽이 반드시 대조해야 한다.
        "affinity_sha256": sha,
        "affinity_pack": str(args.affinity.name),
        "artist_table_sha256": hashlib.sha256(
            json.dumps(affinity["artists"], ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "pairing_note": ("작가 색인은 친화도 팩의 것을 그대로 쓴다. 두 파일은 **짝으로만** "
                         "쓸 수 있다 - artist_table_sha256 이 다르면 읽지 마라."),
        "rid_base": 0,
        "source_corpus": str(args.corpus),
        "builder": "tools/build_artist_general_aggregate.py",
    }

    write_pack(args.out, meta=meta, built=built)
    size = args.out.stat().st_size
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    print(f"\n-> {args.out}  {size/1024**2:.1f}MB  sha256 {digest[:16]}...  "
          f"({time.monotonic()-started:.0f}s)")
    reader = PackReader(args.out)
    for name, (_start, length) in sorted(reader.sections.items(),
                                         key=lambda kv: -kv[1][1]):
        print(f"     {name:>18}: {length/1024**2:7.2f}MB")
    reader.close()

    wanted = [tag for tag in VERIFY_TAGS]
    if not verify_roundtrip(args.out, built, wanted):
        print("\n[!] 왕복 검산 실패 - 산출물을 쓰지 마라.")
        return 1
    if args.tags is not None:
        if not verify_against_parquet(args.out, args.tags, affinity["artists"],
                                      wanted, args.min_count):
            print("\n[!] 전수 주사 검산 실패 - 산출물을 쓰지 마라.")
            return 1
    else:
        print("\n[!] --tags 를 안 줘서 **전수 주사 교차검증을 건너뛰었다**. "
              "배포 전에 한 번은 주고 돌릴 것.")

    print("\n다음:")
    print("  1) 번들 등록 두 곳 (안 하면 배포판에서 조용히 빈다)")
    print("     release_assets/manifests/release_include_exclude_draft.json"
          " -> include.clean_machine_data 에 \"data/artist_tag_general.naiapack\"")
    print("     tools/release_manifest_audit.py -> 허용 목록에 두 형태를 짝으로")
    print("       \"data/artist_tag_general.naiapack\"")
    print("       \"*/data/artist_tag_general.naiapack\"")
    print("  2) 바로 확인:")
    print('     python -c "from core.artist_affinity import default_pack as P;'
          ' p=P(); print(p.state()[\'axes\']);'
          ' print(p.suggest(\'small br\', axis=\'general\')[:3])"')
    print("  3) 리모컨 [검색] 의 [태그] 칸이 열린다(서버 재시작 후).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
