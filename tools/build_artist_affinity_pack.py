"""작가 x 태그 친화도 팩을 굽는다 — `data/artist_tag_affinity.naiapack`.

    python tools/build_artist_affinity_pack.py \
        --corpus C:/VNR/DEV/NAIA-TagSearch-Full-20260912/tag_corpus.full.175.sqlite3 \
        --tags   C:/VNR/DEV/NAIA2.0/NAIA-Portable/user-data/data/tags \
        --out    data/artist_tag_affinity.naiapack

무엇을 담나
    copyright / character 두 축의 역색인(postings) + `행 -> 작가` + `행 -> 등급`.
    general 축은 **담지 않는다** — 이미 배포되는 `.naiamap`(879MB) 안에 있다.
    담으면 256MB 를 중복으로 싣게 된다.

왜 이렇게 만드나
    이 축들의 친화도를 전수 주사로 내면 태그 하나에 49초(참조 구현) 또는 23초
    (NAIA 검색)가 든다. 팩을 읽으면 **60~150ms** 다. 설계 배경과 실측표는
    `docs/ARTIST_TAG_AFFINITY_CONTEXT.md` 와 그 §8 을 볼 것.

⚠️ 이 파일에 박혀 있는 규칙 넷 (전부 실제로 틀렸다가 고친 것)
  * **행 번호는 코퍼스 빌드 하나에 못 박혀 있다.** 원본 sqlite 가 훑은 parquet 175개와
    바이트까지 같아야 `행 -> 작가` 가 맞는다. 파일 이름 정렬이 사전순이라
    `tags_150` 이 `tags_16` **앞**에 선다 - 150개짜리 아카이브로 이으면 앞 41.3%만
    맞고 나머지는 엉뚱한 작가가 붙는다(실측). 그래서 **빌드 때 매니페스트를 대조**하고,
    맞지 않으면 굽기를 거절한다.
  * **postings 는 0-based 로 바꿔 담는다.** 원본 sqlite 와 `.naiamap` 은 1-based 다.
    한 파일 안에 1-based 목록과 0-based 배열을 섞으면 반드시 off-by-one 이 난다
    (실제로 한 번 냈다 - 건수는 198,013 로 그럴듯했고 작가만 79,369명으로 터졌다).
    general 축을 나중에 이 팩과 이을 사람은 `meta.rid_base` 를 볼 것.
  * `banned artist` 는 작가가 아니라 삭제 요청 표식이다. 세기 전에 뗀다.
  * 합작(작가 둘 이상) 행은 버린다 - 기존 `artist_counts.json` 과 같은 자를 써야 한다.

산출물은 스스로를 검산한다(`--verify`, 기본 켜짐): 구운 팩을 다시 열어 표본 태그의
작가 집계를 **parquet 전수 주사와 맞대어** 완전히 같은지 본다. 25초쯤 든다.
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
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
# 이 저장소의 콘솔은 cp949 라 한글 진행 표시가 깨진다(백엔드 print 규약과 같은 이유).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.event_map.index import decode_postings  # noqa: E402
from core.event_map.pack import PackReader, PackWriter  # noqa: E402

SCHEMA = "naia-artist-affinity-v1"
AXES = ("copyright", "character")
# 다 쓰였는지 닫을 때 확인한다 - 끊긴 팩을 읽는 쪽이 절반만 보고 도는 일이 없도록.
REQUIRED_SECTIONS = (
    "meta", "artist_names", "rid_artist", "rid_rating",
    "names_copyright", "post_index_copyright", "postings_copyright",
    "names_character", "post_index_character", "postings_character",
)
BANNED = "banned artist"
RATING_CODE = {"g": 0, "s": 1, "q": 2, "e": 3}
RATING_UNKNOWN = 255
# 검산용 표본. 두 축 + 흔한 것/드문 것을 섞는다.
VERIFY_TAGS = (
    ("copyright", "blue archive"),
    ("copyright", "genshin impact"),
    ("character", "hoshino ai (oshi no ko)"),
    ("character", "hatsune miku"),
)
_VARINT_WIDTH = ((1 << 7, 2), (1 << 14, 3), (1 << 21, 4), (1 << 28, 5))


# --------------------------------------------------------------------- 공통
def sole_artist(value: str) -> str:
    """단일 작가 이름. 합작이면 빈 문자열(= 세지 않는다)."""
    names = [part.strip() for part in value.split(",")]
    names = [name for name in names if name and name != BANNED]
    return names[0] if len(names) == 1 else ""


def resolve_artist_column(series: pd.Series) -> pd.Series:
    name = series.fillna("").astype(str).str.strip()
    has_comma = name.str.contains(",")
    name.loc[has_comma] = name[has_comma].map(sole_artist)
    return name


def varints(values: np.ndarray) -> np.ndarray:
    """LEB128. 한 바이트씩 파이썬으로 돌면 912만 값에 몇 분이 든다."""
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
    """`.naiamap` 과 같은 인코딩: zlib(개수 + (간격-1) varint).

    `decode_postings` 가 `cumsum(deltas + 1) - 1` 로 푸는 것과 짝이다.
    절대값 uint32 로 담는 원본 sqlite 보다 1.6~1.9배 작다(실측).
    """
    deltas = np.diff(np.concatenate(([-1], rids))) - 1
    body = np.concatenate([varints(np.array([rids.size])), varints(deltas)])
    return zlib.compress(body.tobytes(), 6)


def jzlib(obj) -> bytes:
    return zlib.compress(json.dumps(obj, ensure_ascii=False).encode("utf-8"), 6)


# ------------------------------------------------------- 원본 정합성 확인
def check_corpus_matches_tags(db: sqlite3.Connection, tag_dir: Path) -> dict:
    """원본 sqlite 가 훑은 parquet 과 지금 그 폴더가 **같은 것인가**.

    이게 어긋나면 `행 -> 작가` 가 통째로 어긋난다. 굽기 전에 막는 유일한 지점이다.
    """
    row = db.execute("SELECT value FROM metadata WHERE key='source_manifest'").fetchone()
    if row is None:
        raise SystemExit("원본 sqlite 에 source_manifest 가 없다 - 이 코퍼스로는 못 굽는다")
    manifest = json.loads(row[0])
    sha_row = db.execute(
        "SELECT value FROM metadata WHERE key='source_manifest_sha256'").fetchone()
    # ⚠️ 이 값은 sqlite 에 **JSON 문자열로** 들어 있다(`"6796..."` - 따옴표째).
    #    그대로 실으면 `.naiamap` 쪽의 맨 문자열과 영영 안 맞아 버전 게이트가
    #    **조용히 늘 불일치**가 된다. 여기서 벗겨 둔다.
    sha = None
    if sha_row and sha_row[0]:
        raw = str(sha_row[0]).strip()
        try:
            sha = json.loads(raw) if raw.startswith('"') else raw
        except json.JSONDecodeError:
            sha = raw.strip('"')
    listed = {entry["file"]: int(entry["bytes"]) for entry in manifest["files"]}

    local = sorted(tag_dir.glob("tags_*.parquet"))
    have = {path.name: path.stat().st_size for path in local}
    missing = sorted(set(listed) - set(have))
    extra = sorted(set(have) - set(listed))
    resized = sorted(name for name in set(listed) & set(have)
                     if listed[name] != have[name])
    if missing or extra or resized:
        print("[!] parquet 아카이브가 원본 코퍼스와 다르다 - 행 번호를 믿을 수 없다.")
        print(f"    없음 {len(missing)}: {missing[:5]}")
        print(f"    여분 {len(extra)}: {extra[:5]}")
        print(f"    크기 다름 {len(resized)}: {resized[:5]}")
        raise SystemExit(
            "굽기를 멈춘다. 원본 코퍼스를 만들 때 쓴 바로 그 parquet 폴더를 --tags 로 줄 것.")

    # 매니페스트 차례 == 사전순 정렬. 행 번호가 이 차례를 전제한다.
    if [entry["file"] for entry in manifest["files"]] != sorted(listed):
        raise SystemExit("매니페스트 차례가 사전순이 아니다 - 빌더의 전제가 깨졌다")
    print(f"[정합] parquet {len(local)}개 · 바이트 일치 · 차례 일치 "
          f"(manifest sha {(sha or '?')[:12]}...)")
    return {"files": len(local), "sha256": sha, "path": manifest.get("raw_source")}


# ------------------------------------------------------------------- 굽기
def build_side_arrays(tag_dir: Path) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """`행 -> 작가코드` · `행 -> 등급코드` · 작가 이름표.

    작가 코드 **0번은 '세지 않음'**(합작이거나 작가 없음)으로 고정한다. 읽는 쪽이
    빈 문자열을 다시 찾지 않아도 되도록 자리를 못 박아 둔다.
    """
    started = time.monotonic()
    names, ratings = [], []
    for path in sorted(tag_dir.glob("tags_*.parquet")):
        frame = pd.read_parquet(path, columns=["artist", "rating"], engine="pyarrow")
        names.append(resolve_artist_column(frame["artist"]))
        ratings.append(frame["rating"].astype(str).str[0].map(RATING_CODE)
                       .fillna(RATING_UNKNOWN))
    artist = pd.concat(names, ignore_index=True)
    rating = pd.concat(ratings, ignore_index=True).astype(np.uint8).to_numpy()

    codes, uniques = pd.factorize(artist)
    empty = int(np.flatnonzero(uniques == "")[0])
    order = [empty] + [i for i in range(len(uniques)) if i != empty]
    remap = np.empty(len(uniques), dtype=np.int64)
    remap[np.asarray(order)] = np.arange(len(order))
    codes = remap[codes].astype(np.uint32)
    table = [""] + [str(uniques[i]) for i in order[1:]]

    counted = int((codes != 0).sum())
    print(f"[곁들이] {time.monotonic()-started:.1f}s 행 {len(codes):,} · "
          f"작가 {len(table)-1:,}명 · 단일작가 행 {counted:,} "
          f"({counted/len(codes):.1%}) · 등급 "
          f"{dict(zip(*np.unique(rating, return_counts=True)))}")
    return codes, rating, table


def build_axis(db: sqlite3.Connection, field: str, rows: int
               ) -> tuple[list[str], np.ndarray, bytes, dict]:
    """한 축의 이름표 · post_index · postings 덩어리."""
    started = time.monotonic()
    entries = db.execute(
        "SELECT t.name, p.data, p.cardinality FROM tags t JOIN postings p ON p.tag=t.id "
        "WHERE t.field=? ORDER BY t.id", (field,)).fetchall()
    names: list[str] = []
    offsets = [0]
    chunks: list[bytes] = []
    total = 0
    src_bytes = 0
    for name, blob, cardinality in entries:
        src_bytes += len(blob)
        raw = array('I')
        raw.frombytes(zlib.decompress(blob))
        rids = np.sort(np.frombuffer(raw, dtype=np.uint32).astype(np.int64))
        if rids.size != cardinality:
            raise SystemExit(f"{field}/{name}: postings 개수가 안 맞는다")
        if rids[0] < 1 or rids[-1] > rows:
            raise SystemExit(f"{field}/{name}: 행 번호가 범위 밖이다 "
                             f"({rids[0]}..{rids[-1]}, rows={rows})")
        # 1-based -> 0-based. 이 한 줄이 이 팩의 유일한 자리 옮김이다.
        encoded = encode_postings(rids - 1)
        chunks.append(encoded)
        offsets.append(offsets[-1] + len(encoded))
        names.append(name)
        total += int(rids.size)
    body = b"".join(chunks)
    stats = {"tags": len(names), "incidences": total,
             "sqlite_bytes": src_bytes, "pack_bytes": len(body)}
    print(f"[{field:>9}] {time.monotonic()-started:.0f}s 태그 {len(names):,} · "
          f"게시물 {total:,} · sqlite {src_bytes/1024**2:.1f}MB -> "
          f"{len(body)/1024**2:.1f}MB ({src_bytes/max(len(body),1):.2f}x)")
    return names, np.asarray(offsets, dtype=np.uint64), body, stats


def write_pack(out: Path, *, meta: dict, axes: dict, codes: np.ndarray,
               rating: np.ndarray, artists: list[str]) -> None:
    """`*.part` 로 쓰고 다 되면 제자리에 옮긴다 - 끊긴 빌드가 팩 행세를 못 하도록."""
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_suffix(out.suffix + ".part")
    part.unlink(missing_ok=True)
    writer = PackWriter(part, required=REQUIRED_SECTIONS)
    try:
        writer.add("meta", json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        for field in AXES:
            names, offsets, body = axes[field]
            writer.add(f"names_{field}", jzlib(names))
            writer.add(f"post_index_{field}", offsets.tobytes())
            writer.add(f"postings_{field}", body)
        writer.add("artist_names", jzlib(artists))
        writer.add("rid_artist", zlib.compress(codes.tobytes(), 6))
        writer.add("rid_rating", zlib.compress(rating.tobytes(), 6))
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
def scan_truth(tag_dir: Path, wanted: list[tuple[str, str]]) -> dict:
    """parquet 전수 주사로 낸 정답. 한 번 훑으며 태그를 모두 본다."""
    started = time.monotonic()
    patterns = {key: r'(^|,)\s*' + re.escape(key[1]) + r'\s*(,|$)' for key in wanted}
    tally = {key: Counter() for key in wanted}
    for path in sorted(tag_dir.glob("tags_*.parquet")):
        frame = pd.read_parquet(path, columns=["artist", "copyright", "character"],
                                engine="pyarrow")
        artist = resolve_artist_column(frame["artist"])
        for key in wanted:
            field = key[0]
            column = pa.array(frame[field].fillna("").astype(str), from_pandas=True)
            mask = pc.fill_null(pc.match_substring_regex(column, patterns[key]),
                                False).to_numpy(zero_copy_only=False)
            hit = artist[mask]
            tally[key].update(hit[hit != ""].tolist())
    print(f"[검산] 전수 주사 {time.monotonic()-started:.0f}s ({len(wanted)}개 태그 동시)")
    return tally


def verify(out: Path, tag_dir: Path, wanted: list[tuple[str, str]]) -> bool:
    reader = PackReader(out)
    try:
        meta = reader.json_of("meta")
        codes = np.frombuffer(zlib.decompress(reader.bytes_of("rid_artist")),
                              dtype=np.uint32)
        artists = json.loads(zlib.decompress(reader.bytes_of("artist_names")))
        rating = np.frombuffer(zlib.decompress(reader.bytes_of("rid_rating")),
                               dtype=np.uint8)
        if codes.size != meta["rows"] or rating.size != meta["rows"]:
            print("[검산] 곁들이 배열 길이가 meta 와 다르다")
            return False
        truth = scan_truth(tag_dir, wanted)
        ok = True
        for field, tag in wanted:
            names = json.loads(zlib.decompress(reader.bytes_of(f"names_{field}")))
            index = np.frombuffer(reader.bytes_of(f"post_index_{field}"), dtype=np.uint64)
            try:
                tid = names.index(tag)
            except ValueError:
                print(f"[검산] {field}/{tag}: 팩 어휘에 없다")
                ok = False
                continue
            start, end = int(index[tid]), int(index[tid + 1])
            blob = reader.bytes_of(f"postings_{field}")[start:end]
            rids = decode_postings(zlib.decompress(blob))
            picked = codes[rids]
            picked = picked[picked != 0]
            counts = np.bincount(picked, minlength=len(artists))
            got = Counter({artists[i]: int(counts[i])
                           for i in np.flatnonzero(counts)})
            same = got == truth[(field, tag)]
            ok &= same
            print(f"[검산] {field}/{tag}: 게시물 {rids.size:,} · 작가 "
                  f"{len(got):,} · 건수 {sum(got.values()):,} · 전수 주사와 "
                  f"{'일치' if same else '불일치'}")
            if not same:
                diff = [(k, got.get(k, 0), truth[(field, tag)].get(k, 0))
                        for k in set(got) | set(truth[(field, tag)])
                        if got.get(k, 0) != truth[(field, tag)].get(k, 0)]
                print(f"        어긋난 작가 {len(diff):,} 표본={diff[:5]}")
        return bool(ok)
    finally:
        reader.close()


# ------------------------------------------------------------------- main
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", required=True, type=Path,
                        help="tag_corpus.full.175.sqlite3 (5개 필드 역색인 원본)")
    parser.add_argument("--tags", required=True, type=Path,
                        help="원본 코퍼스를 만들 때 쓴 parquet 폴더")
    parser.add_argument("--out", type=Path,
                        default=REPO / "data" / "artist_tag_affinity.naiapack")
    parser.add_argument("--force", action="store_true", help="기존 산출물을 덮어쓴다")
    parser.add_argument("--no-verify", dest="verify", action="store_false",
                        help="전수 주사 검산을 건너뛴다(25초 절약, 권하지 않는다)")
    args = parser.parse_args()

    if args.out.exists() and not args.force:
        raise SystemExit(f"이미 있다: {args.out}  (덮어쓰려면 --force)")
    if not args.corpus.is_file():
        raise SystemExit(f"원본 코퍼스가 없다: {args.corpus}")
    if not args.tags.is_dir():
        raise SystemExit(f"parquet 폴더가 없다: {args.tags}")

    started = time.monotonic()
    db = sqlite3.connect(args.corpus)
    source = check_corpus_matches_tags(db, args.tags)
    rows = int(db.execute("SELECT COUNT(*) FROM records").fetchone()[0])

    codes, rating, artists = build_side_arrays(args.tags)
    if codes.size != rows:
        raise SystemExit(f"parquet 행 {codes.size:,} != 코퍼스 records {rows:,}")

    axes, stats = {}, {}
    for field in AXES:
        names, offsets, body, info = build_axis(db, field, rows)
        axes[field] = (names, offsets, body)
        stats[field] = info

    meta = {
        "schema": SCHEMA,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": rows,
        "axes": list(AXES),
        "axis_stats": stats,
        "artists": len(artists) - 1,
        "rating_codes": RATING_CODE,
        "rating_unknown": RATING_UNKNOWN,
        # 읽는 쪽이 반드시 보아야 하는 두 줄.
        "rid_base": 0,
        "rid_note": ("이 팩의 postings 는 0-based 행 번호다(배열 첨자 그대로). "
                     "원본 sqlite 와 event_map .naiamap 은 1-based 이므로 general 축을 "
                     "이 팩의 rid_artist 와 이을 때는 반드시 1을 빼라."),
        "artist_code_0": "세지 않음(합작이거나 작가 없음)",
        "min_posts": None,
        "min_posts_note": ("문턱을 데이터에 걸지 않았다 - 표본이 얇은 작가는 화면에서 "
                           "Wilson 하한으로 눌러라. 문턱을 담아도 팩 크기는 안 변한다."),
        "general_axis": ("이 팩에 없다. event_map .naiamap(1-based)이 갖고 있다 - "
                         "중복해 담으면 256MB 가 는다."),
        "source": source,
        "source_corpus": str(args.corpus),
        "builder": "tools/build_artist_affinity_pack.py",
    }

    write_pack(args.out, meta=meta, axes=axes, codes=codes, rating=rating,
               artists=artists)
    size = args.out.stat().st_size
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    print(f"\n-> {args.out}  {size/1024**2:.1f}MB  sha256 {digest[:16]}...  "
          f"({time.monotonic()-started:.0f}s)")
    reader = PackReader(args.out)
    for name, (_start, length) in sorted(reader.sections.items(),
                                         key=lambda kv: -kv[1][1]):
        print(f"     {name:>22}: {length/1024**2:7.2f}MB")
    reader.close()

    if args.verify and not verify(args.out, args.tags, list(VERIFY_TAGS)):
        print("\n[!] 검산 실패 - 산출물을 쓰지 마라.")
        return 1

    print("\n다음:")
    print("  1) 번들 등록 두 곳 (안 하면 배포판에서 조용히 빈다)")
    print("     release_assets/manifests/release_include_exclude_draft.json"
          " -> include.clean_machine_data 에 \"data/artist_tag_affinity.naiapack\"")
    print("     tools/release_manifest_audit.py -> 허용 목록에 두 형태를 짝으로")
    print("       \"data/artist_tag_affinity.naiapack\"")
    print("       \"*/data/artist_tag_affinity.naiapack\"")
    print("  2) python -c \"from core.artist_affinity import ArtistAffinityPack as P;"
          " p=P(); print(p.state()); print(p.affinity('blue archive')[:3])\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
