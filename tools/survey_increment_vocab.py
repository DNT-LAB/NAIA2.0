"""증분 코퍼스(tags_150~174)의 어휘를 배포본(tags_000~149)과 대조해 세 표를 만든다.

  artists_all.csv        증분에 등장한 아티스트 **전체**(빈도) + 배포본 빈도 + 사전 포함 여부
  characters_new.csv     배포본에 한 번도 없던 캐릭터(데뷔) + 사전 포함 여부
  general_new.csv        배포본에 한 번도 없던 general 태그

"신규" 판정은 문자열 정확 일치다(코퍼스 규약: 소문자 · 공백 · `name (series)`).
⚠️ 사전에 없다 != 신규. 캐릭터 사전은 빈도 하한 20 이 걸려 있어 롱테일이 빠져 있다.
   그래서 `in_dict` 열을 따로 둔다 — 배포본 빈도 0 이면서 사전에 있는 경우는 없어야 정상.

사용
  python tools/survey_increment_vocab.py --inc <25버킷 dir> --base <150버킷 dir> --out <dir>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

_NUM = re.compile(r"(\d+)")


def bucket_files(d: Path) -> list[Path]:
    files = [p for p in d.glob("tags_*.parquet")]
    return sorted(files, key=lambda p: int(_NUM.search(p.stem).group(1)))


def count_column(files: list[Path], col: str, label: str) -> tuple[pd.Series, int]:
    """열의 태그 빈도(태그 -> 행 수)와 총 행 수. 벡터화(pyarrow) 로 센다."""
    acc: dict[str, int] = {}
    rows = 0
    t0 = time.time()
    for i, f in enumerate(files, 1):
        tbl = pq.read_table(f, columns=[col])
        rows += tbl.num_rows
        arr = tbl.column(col).combine_chunks()
        arr = pc.drop_null(arr)
        if len(arr) == 0:
            continue
        flat = pc.list_flatten(pc.split_pattern(arr, ", "))
        vc = pc.value_counts(flat)
        vals = vc.field("values").to_pylist()
        cnts = vc.field("counts").to_pylist()
        for v, c in zip(vals, cnts):
            if v:
                acc[v] = acc.get(v, 0) + c
        if i % 25 == 0 or i == len(files):
            print(f"  [{label}/{col}] {i}/{len(files)}  rows={rows:,}  vocab={len(acc):,}  "
                  f"{time.time()-t0:.0f}s", flush=True)
    return pd.Series(acc, dtype="int64"), rows


def series_of(tag: str) -> str:
    """`name (series)` -> `series`. 변형 태그 `name (x) (series)` 는 마지막 괄호."""
    m = re.search(r"\(([^()]*)\)\s*$", tag)
    return m.group(1) if m else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inc", required=True, help="증분 버킷 디렉터리 (tags_150~174)")
    ap.add_argument("--base", required=True, help="배포본 버킷 디렉터리 (tags_000~149)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    inc_files = bucket_files(Path(args.inc))
    base_files = bucket_files(Path(args.base))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"[입력] 증분 {len(inc_files)}개 · 배포본 {len(base_files)}개")

    # ---- 사전 ---------------------------------------------------------------
    from danbooru_character import character_dict_count          # noqa: E402
    from artist_dictionary import artist_dict                    # noqa: E402
    char_dict = set(character_dict_count)
    art_dict = set(artist_dict)
    print(f"[사전] 캐릭터 {len(char_dict):,} · 아티스트 {len(art_dict):,}")

    # ---- 증분 ---------------------------------------------------------------
    inc_art, inc_rows = count_column(inc_files, "artist", "inc")
    inc_chr, _ = count_column(inc_files, "character", "inc")
    inc_gen, _ = count_column(inc_files, "general", "inc")
    ids = pq.read_table(inc_files[0], columns=["id"]).column("id")
    id_min = pc.min(ids).as_py()
    ids = pq.read_table(inc_files[-1], columns=["id"]).column("id")
    id_max = pc.max(ids).as_py()
    density = inc_rows / (id_max - id_min + 1)
    print(f"[증분] rows={inc_rows:,}  id {id_min:,}~{id_max:,}  밀도 {density:.1%}")
    if density < 0.9:
        raise SystemExit("증분 밀도가 90% 미만 - 부분 산출물이다. 중단.")

    # ---- 배포본 -------------------------------------------------------------
    base_art, base_rows = count_column(base_files, "artist", "base")
    base_chr, _ = count_column(base_files, "character", "base")
    base_gen, _ = count_column(base_files, "general", "base")
    print(f"[배포본] rows={base_rows:,}")

    # ---- 1. 아티스트 전체 -----------------------------------------------------
    art = pd.DataFrame({"count_inc": inc_art})
    art["count_base"] = base_art.reindex(art.index).fillna(0).astype("int64")
    art["in_artist_dict"] = art.index.isin(art_dict)
    art["is_new"] = art["count_base"] == 0
    art = art.sort_values("count_inc", ascending=False)
    art.index.name = "artist"
    art.to_csv(out / "artists_all.csv", encoding="utf-8-sig")
    art.reset_index().to_parquet(out / "artists_all.parquet", index=False)

    # ---- 2. 신규 캐릭터 -------------------------------------------------------
    chr_ = pd.DataFrame({"count_inc": inc_chr})
    chr_["count_base"] = base_chr.reindex(chr_.index).fillna(0).astype("int64")
    chr_["in_char_dict"] = chr_.index.isin(char_dict)
    chr_.index.name = "character"
    chr_all = chr_.sort_values("count_inc", ascending=False)
    chr_all.to_csv(out / "characters_all.csv", encoding="utf-8-sig")
    chr_new = chr_all[chr_all["count_base"] == 0].copy()
    chr_new["series"] = [series_of(t) for t in chr_new.index]
    chr_new.to_csv(out / "characters_new.csv", encoding="utf-8-sig")
    chr_new.reset_index().to_parquet(out / "characters_new.parquet", index=False)

    # ---- 3. 신규 general -------------------------------------------------------
    gen = pd.DataFrame({"count_inc": inc_gen})
    gen["count_base"] = base_gen.reindex(gen.index).fillna(0).astype("int64")
    gen.index.name = "tag"
    gen_new = gen[gen["count_base"] == 0].sort_values("count_inc", ascending=False)
    gen_new[["count_inc"]].to_csv(out / "general_new.csv", encoding="utf-8-sig")
    gen_new[["count_inc"]].reset_index().to_parquet(out / "general_new.parquet", index=False)

    summary = {
        "increment": {"rows": inc_rows, "id_min": id_min, "id_max": id_max,
                      "density": round(density, 4), "files": len(inc_files)},
        "base": {"rows": base_rows, "files": len(base_files)},
        "artists": {
            "total_in_increment": int(len(art)),
            "new_vs_base": int(art["is_new"].sum()),
            "not_in_artist_dict": int((~art["in_artist_dict"]).sum()),
            "new_and_ge_20": int(((art["is_new"]) & (art["count_inc"] >= 20)).sum()),
        },
        "characters": {
            "total_in_increment": int(len(chr_)),
            "new_vs_base": int(len(chr_new)),
            "new_in_dict_anomaly": int(chr_new["in_char_dict"].sum()),
            "new_and_ge_20": int((chr_new["count_inc"] >= 20).sum()),
            "new_series": int(chr_new["series"].nunique()),
        },
        "general": {
            "total_in_increment": int(len(gen)),
            "new_vs_base": int(len(gen_new)),
            "new_and_ge_20": int((gen_new["count_inc"] >= 20).sum()),
            "new_and_ge_100": int((gen_new["count_inc"] >= 100).sum()),
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
