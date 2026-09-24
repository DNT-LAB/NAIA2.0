# -*- coding: utf-8 -*-
"""태그 x 등급(G/S/Q/E) 등장 횟수 표를 만든다 (사용자 지정 2026-09-24).

쓰임: 태그 미리보기 툴팁에 "이 태그가 등급별로 몇 번 나오나" 를 보여 준다. 검색 순서 최적화
(개수가 적은 태그부터 거르기, search-quick-redesign 의 TODO)에도 같은 표를 쓴다.

방법: 아카이브 파일마다 태그 칸을 ', ' 로 갈라 펴고 그 행의 등급과 짝지어 (tag, rating) 으로
센 뒤 합친다. 같은 id 가 여러 파일에 있으면 **뒤(새) 파일의 것만** 센다(검색의 _dedup_by_id 와
같은 뜻 - 겹친 행을 두 번 세면 수가 부푼다).

    python tools/build_tag_rating_counts.py                      # 기본: 런타임 아카이브 -> 옆에 저장
    python tools/build_tag_rating_counts.py --tags-dir X --out Y.parquet

출력 parquet: tag(str) · g · s · q · e · total(int64), total 내림차순. 스키마 메타 `naia` 에
만든 시각·파일 수·행 수·원본 지문(파일 이름+크기)을 적는다 - 아카이브가 바뀌었는지 이걸로 안다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parents[1]
RATINGS = ("g", "s", "q", "e")
DEFAULT_COLUMNS = ("general", "character", "copyright", "artist", "meta")
OUT_NAME = "tag_rating_counts.parquet"


def default_tags_dir() -> Path:
    """런타임 아카이브가 권위(앱이 검색하는 곳) - 없으면 저장소의 개발용 사본."""
    runtime = Path(os.environ.get("NAIA_USER_DATA_DIR") or Path(os.environ.get("APPDATA", "")) / "NAIA") / "data" / "tags"
    if any(runtime.glob("tags_*.parquet")):
        return runtime
    return REPO / "data" / "tags"


def _sort_key(path: Path):
    match = re.search(r"(\d+)", path.stem)
    return (int(match.group(1)) if match else 10**9, path.name)


def archive_files(tags_dir: Path) -> list[Path]:
    return sorted((p for p in tags_dir.glob("tags_*.parquet") if p.is_file()), key=_sort_key)


def fingerprint(files: list[Path]) -> str:
    h = hashlib.sha256()
    for path in files:
        h.update(f"{path.name}:{path.stat().st_size}\n".encode("utf-8"))
    return h.hexdigest()[:16]


def keep_masks(files: list[Path], workers: int) -> tuple[list[np.ndarray | None], int]:
    """파일별 '셀 행' 마스크. 같은 id 는 가장 뒤 파일의 것만 남긴다. 겹침이 없으면 None."""
    with ThreadPoolExecutor(workers) as ex:
        ids = list(ex.map(lambda p: pq.read_table(p, columns=["id"])["id"].to_numpy(), files))
    all_ids = np.concatenate(ids)
    file_of = np.concatenate([np.full(len(a), i, dtype=np.int32) for i, a in enumerate(ids)])
    # 뒤에서부터 처음 나온 것 = 가장 뒤 파일의 것.
    rev = all_ids[::-1]
    _, first_rev = np.unique(rev, return_index=True)
    keep = np.zeros(len(all_ids), dtype=bool)
    keep[len(all_ids) - 1 - first_rev] = True
    duplicates = int(len(all_ids) - keep.sum())
    masks: list[np.ndarray | None] = []
    offset = 0
    for arr in ids:
        part = keep[offset:offset + len(arr)]
        masks.append(None if part.all() else part)
        offset += len(arr)
    del file_of
    return masks, duplicates


def count_file(path: Path, columns: tuple[str, ...], mask: np.ndarray | None):
    table = pq.read_table(path, columns=[*columns, "rating"])
    if mask is not None:
        table = table.filter(pa.array(mask))
    parts = []
    for column in columns:
        lists = pc.split_pattern(pc.fill_null(table[column], ""), ", ")
        parent = pc.list_parent_indices(lists)
        parts.append(pa.table({
            "tag": pc.utf8_trim_whitespace(pc.list_flatten(lists)),
            "rating": pc.take(table["rating"], parent),
        }))
    flat = pa.concat_tables(parts)
    flat = flat.filter(pc.not_equal(flat["tag"], ""))
    return table.num_rows, flat.group_by(["tag", "rating"]).aggregate([([], "count_all")])


def build(tags_dir: Path, out: Path, columns: tuple[str, ...], workers: int) -> dict:
    files = archive_files(tags_dir)
    if not files:
        raise SystemExit(f"no tags_*.parquet in {tags_dir}")
    t0 = time.perf_counter()
    masks, duplicates = keep_masks(files, workers)
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(lambda pm: count_file(pm[0], columns, pm[1]), zip(files, masks)))
    merged = pa.concat_tables([r[1] for r in results]).group_by(["tag", "rating"]).aggregate(
        [("count_all", "sum")])
    # 넓게: tag -> g/s/q/e
    tags = merged["tag"]
    uniq = pc.unique(tags)
    index = pc.index_in(tags, value_set=uniq).to_numpy()
    counts = merged["count_all_sum"].to_numpy()
    wide = {r: np.zeros(len(uniq), dtype=np.int64) for r in RATINGS}
    rating = merged["rating"].to_pylist()
    rating_arr = np.array(rating, dtype=object)
    for r in RATINGS:
        sel = rating_arr == r
        np.add.at(wide[r], index[sel], counts[sel])
    total = sum(wide.values())
    order = np.argsort(-total, kind="stable")
    rows = sum(r[0] for r in results)
    meta = {
        "v": 1,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tags_dir": str(tags_dir),
        "files": len(files),
        "rows": rows,
        "duplicate_rows_skipped": duplicates,
        "columns": list(columns),
        "source_fingerprint": fingerprint(files),
        "unknown_ratings": sorted({r for r in rating if r not in RATINGS and r is not None}),
    }
    table = pa.table({
        "tag": pc.take(uniq, pa.array(order)),
        **{r: pa.array(wide[r][order]) for r in RATINGS},
        "total": pa.array(total[order]),
    }).replace_schema_metadata({"naia": json.dumps(meta, ensure_ascii=False)})
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(out)
    meta["seconds"] = round(time.perf_counter() - t0, 1)
    meta["tags"] = table.num_rows
    meta["out"] = str(out)
    meta["out_mb"] = round(out.stat().st_size / 1024 / 1024, 2)
    return meta


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tags-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None, help=f"기본: <tags-dir>/../{OUT_NAME}")
    parser.add_argument("--columns", default=",".join(DEFAULT_COLUMNS))
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    args = parser.parse_args(argv)
    tags_dir = (args.tags_dir or default_tags_dir()).resolve()
    out = (args.out or tags_dir.parent / OUT_NAME).resolve()
    meta = build(tags_dir, out, tuple(c.strip() for c in args.columns.split(",") if c.strip()), args.workers)
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
