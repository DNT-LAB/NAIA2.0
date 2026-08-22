"""기존 태그 코퍼스 뒤에 신규 post 를 **증분으로** 이어 붙인다.

배경
----
`data/tags/tags_000..149.parquet` 는 2016-01 ~ **2025-09-19**(post id 9,991,379)까지다.
그 뒤로 Danbooru 는 계속 쌓였고, HuggingFace 에 2026 크롤 스냅샷이 올라와 있다.
전체를 다시 만들 필요는 없다 - **마지막 id 다음부터 끝까지**만 받아 새 버킷으로 붙인다.

기본 원본: `BootsofLagrangian/danbooru-multitier-captions-202606`
  post_id 1 … 11,581,022 (최신 post 2026-06-13), 11,531,807행 / 14.6GB.
  ⚠️ **id 순으로 정렬돼 있지 않다** — 첫 행이 2017년, 마지막 행에 2025·2026이 섞여 있다.
  그래서 파일을 전부 훑어야 한다. 대신 필요한 11개 컬럼만 읽으면 캡션 본문(용량의
  대부분)을 건너뛰므로 실제 전송량은 훨씬 작다.

출력 형식(기존과 **바이트 단위로 같은 규약**, 실측으로 확정)
------------------------------------------------------------
  id            int64
  copyright     string   ", " 결합
  character     string   ", " 결합
  artist        string   ", " 결합
  general       string   ", " 결합
  meta          string   ", " 결합
  rating        string   g/s/q/e
  score         int64
  created_at    string   ISO + 밀리초 + 오프셋  예: 2025-09-19T23:59:57.450-04:00
  tokens        double   len(CLIPTokenizer(general).input_ids)   ← 특수토큰 포함
  image_width   int64
  image_height  int64

태그 문자열 규약(실측 확인)
  Danbooru 원형은 공백 구분 + 밑줄이 낱말 사이다: `black_gloves long_hair`
  기존 코퍼스는 낱말 사이 **밑줄을 공백으로 바꾼다**.
  괄호는 그대로 둔다: `hina_(blue_archive)` -> `hina (blue archive)`.

  ⚠️ **이모티콘 태그는 예외다 — 밑줄을 그대로 둔다.**
  이 파일의 옛 주석은 "이모티콘도 예외가 아니다(`^_^` -> `^ ^`)" 라고 적고 있었는데
  **틀렸다.** 배포본 150버킷을 전수 스캔하니 밑줄이 살아 있는 태그가 정확히 17종,
  총 236,846회 있었고 전부 이모티콘이었다(`^_^` 80,207 · `>_<` 44,213 · `|_|` 11,224 …).
  그 주석을 믿고 만든 첫 증분은 이 17종을 전부 `^ ^` 꼴로 뭉갰다.

  이게 왜 중요한가: Auto-Hide 목록·와일드카드·태그 필터는 **문자열 정확 일치**로
  태그를 찾는다. 한 글자만 달라도 그 태그는 영영 안 걸린다. 실제로 V5 추천 프리셋의
  auto_hide 에 `|_|` 가 들어 있다.

⚠️ 배포 시 같이 해야 하는 것
  - `TAG_ARCHIVE_EXPECTED_COUNT`(core/runtime_install_manager.py)가 150 으로 박혀 있다.
    파일 수가 늘면 **같이 올려야** 설치 검증이 통과한다.
  - 재배포용 zip 은 **이름을 반드시 바꾼다.** 다운로더가 이름만 보고 존재를 판정해서,
    같은 이름으로 덮으면 기존 설치가 옛 데이터를 영영 쓴다.

사용
----
  python tools/build_tag_corpus_increment.py --dry-run          # 계획만 출력
  python tools/build_tag_corpus_increment.py --limit-files 3    # 앞 3개 파일로 예행
  python tools/build_tag_corpus_increment.py                    # 전체 실행
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TAGS_DIR = REPO_ROOT / "data" / "tags"
BUCKET_INDEX = REPO_ROOT / "data" / "tag_bucket_dates.json"

DEFAULT_DATASET = "BootsofLagrangian/danbooru-multitier-captions-202606"
CLIP_MODEL = "openai/clip-vit-large-patch14"

# 기존 버킷의 최근 크기. 새 버킷도 같은 크기로 끊는다.
BUCKET_ROWS = 65_658

OUT_COLUMNS = [
    "id", "copyright", "character", "artist", "general", "meta",
    "rating", "score", "created_at", "tokens", "image_width", "image_height",
]

# 원본에서 실제로 읽는 컬럼만. 캡션 본문을 빼는 것이 전송량 절감의 핵심이다.
SRC_COLUMNS = [
    "post_id", "tag_string_copyright", "tag_string_character", "tag_string_artist",
    "tag_string_general", "tag_string_meta", "rating", "score", "created_at",
    "image_width", "image_height",
]

TAG_FIELDS = {
    "copyright": "tag_string_copyright",
    "character": "tag_string_character",
    "artist": "tag_string_artist",
    "general": "tag_string_general",
    "meta": "tag_string_meta",
}

_ISO_MS = re.compile(r"\.\d{3}")


# 밑줄을 **그대로 두는** 태그. 배포본 150버킷 전수 스캔에서 밑줄이 살아 있던 것이
# 정확히 이 17종이었다(전부 `general` 열의 이모티콘, 합계 236,846회).
#
# ⚠️ 규칙을 문법으로 추측하지 않고 **배포본 어휘를 그대로 권위로 삼는다.** `o_o`
# `0_0` `x_x` `u_u` `3_3` `6_9` 처럼 영숫자가 섞인 것이 8종이라, "기호만 있으면
# 보존" 같은 규칙으로는 절반을 놓친다.
EMOTICON_TAGS = frozenset({
    "^_^", ">_<", "@_@", "+_+", "=_=", "|_|", "o_o", "0_0", "u_u",
    ">_o", "x_x", "._.", "<|>_<|>", "<o>_<o>", "3_3", "6_9", "+_-",
    # 배포본에는 없지만 원본에 3회 있다. `>_o` 와 같은 계열이라 같이 지킨다 -
    # 공백으로 바꾸면 어느 쪽 규약과도 안 맞는 `> @` 가 된다.
    ">_@",
})


def normalize_tags(raw: object) -> object:
    """`black_gloves long_hair` -> `black gloves, long hair`.

    ⚠️ 이모티콘 태그(`EMOTICON_TAGS`)는 밑줄을 그대로 둔다 - 그쪽은 밑줄이 낱말
    구분이 아니라 **글자 자체**다. 위 모듈 주석 참조.

    빈 값은 None 으로 둔다 - 기존 코퍼스도 빈 문자열이 아니라 null 이다
    (character 9.98% / meta 3.9% 가 null).
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    tags = [t if t in EMOTICON_TAGS else t.replace("_", " ")
            for t in s.split() if t]
    return ", ".join(tags) if tags else None


def normalize_created_at(raw: object) -> object:
    """ISO + 밀리초 + 오프셋으로 맞춘다.

    기존 코퍼스는 100% 가 `2025-09-19T23:59:57.450-04:00` 꼴이다. 원본은 밀리초가
    없을 수 있으므로(`...T06:34:44-04:00`) 그때만 `.000` 을 채워 넣는다.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace(" ", "T", 1) if " " in s and "T" not in s else s
    if _ISO_MS.search(s):
        return s
    # 오프셋(+09:00 / -04:00 / Z) 앞에 밀리초를 끼운다.
    m = re.search(r"([+-]\d{2}:\d{2}|Z)$", s)
    if not m:
        return s + ".000"
    return s[: m.start()] + ".000" + m.group(1)


def existing_state() -> tuple[int, int, list[dict]]:
    """(마지막 id, 마지막 버킷 번호, 버킷 인덱스). 인덱스가 없으면 파일에서 유도."""
    buckets: list[dict] = []
    if BUCKET_INDEX.is_file():
        buckets = json.loads(BUCKET_INDEX.read_text(encoding="utf-8")).get("buckets", [])
    if buckets:
        return int(buckets[-1]["max_id"]), int(buckets[-1]["bucket"]), buckets

    import pyarrow.parquet as pq

    files = sorted(TAGS_DIR.glob("tags_*.parquet"))
    if not files:
        raise SystemExit(f"기존 코퍼스를 찾지 못했습니다: {TAGS_DIR}")
    last = pq.read_table(files[-1], columns=["id"]).column("id").to_pylist()
    num = int(re.search(r"(\d+)", files[-1].stem).group(1))
    return max(last), num, []


def source_files(dataset: str, limit: int | None, skip: int = 0) -> list[str]:
    """원본 parquet 목록. 로컬 디렉터리면 그대로, 아니면 HF 경로로 만든다.

    `skip` 은 두 곳에 쓴다: 97개를 훑다 끊겼을 때 이어받기, 그리고 시험 실행.
    ⚠️ 원본이 id 순이 아니라서 **앞쪽 파일에는 신규 id 가 아예 없다**(실측: 0번·1번
    파일에서 0건). 시험할 때는 뒤쪽을 건너뛰어 잡아야 의미가 있다.
    """
    local = Path(dataset)
    if local.is_dir():
        found = sorted(str(p) for p in local.rglob("*.parquet"))
    else:
        from huggingface_hub import HfApi

        files = sorted(
            f for f in HfApi().list_repo_files(dataset, repo_type="dataset")
            if f.endswith(".parquet")
        )
        found = [f"hf://datasets/{dataset}/{f}" for f in files]
    found = found[skip:]
    return found[:limit] if limit else found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default=DEFAULT_DATASET,
                    help="HF 데이터셋 id 또는 parquet 이 들어 있는 로컬 디렉터리")
    ap.add_argument("--out", default=str(TAGS_DIR), help="새 버킷을 쓸 디렉터리")
    ap.add_argument("--limit-files", type=int, default=None, help="N개 파일만 (예행용)")
    ap.add_argument("--skip-files", type=int, default=0, help="앞 N개 건너뛰기 (이어받기/시험)")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 계획만 출력")
    args = ap.parse_args()

    import pandas as pd

    max_id, last_bucket, buckets = existing_state()
    print(f"[기존] 마지막 id={max_id:,}  마지막 버킷=#{last_bucket}  버킷 {len(buckets)}개")

    files = source_files(args.dataset, args.limit_files, args.skip_files)
    print(f"[원본] {args.dataset}  parquet {len(files)}개"
          + (f" (앞 {args.limit_files}개만)" if args.limit_files else ""))
    if args.dry_run:
        for f in files[:3]:
            print(f"        {f}")
        if len(files) > 3:
            print(f"        ... 외 {len(files)-3}개")
        print(f"[계획] post_id > {max_id:,} 인 행만 모아 정렬 -> "
              f"{BUCKET_ROWS:,}행씩 tags_{last_bucket+1:03d}.parquet 부터 기록")
        print("       (--dry-run 이라 아무것도 쓰지 않았습니다)")
        return 0

    frames = []
    kept = 0
    for i, path in enumerate(files, 1):
        try:
            df = pd.read_parquet(path, columns=SRC_COLUMNS)
        except Exception as exc:                       # noqa: BLE001
            print(f"  [{i}/{len(files)}] 실패 {path}: {exc}")
            continue
        df = df[df["post_id"] > max_id]
        if len(df):
            frames.append(df)
            kept += len(df)
        print(f"  [{i}/{len(files)}] +{len(df):,}  누적 {kept:,}", flush=True)

    if not frames:
        print("[결과] 새로 붙일 행이 없습니다.")
        return 0

    merged = pd.concat(frames, ignore_index=True)
    before = len(merged)
    merged = merged.drop_duplicates(subset=["post_id"]).sort_values("post_id")
    print(f"[정리] {before:,} -> {len(merged):,} (중복 {before - len(merged):,} 제거, id 순 정렬)")

    out = pd.DataFrame({"id": merged["post_id"].astype("int64")})
    for dst, src in TAG_FIELDS.items():
        out[dst] = merged[src].map(normalize_tags)
    out["rating"] = merged["rating"].astype(str)
    out["score"] = merged["score"].fillna(0).astype("int64")
    out["created_at"] = merged["created_at"].map(normalize_created_at)

    print("[토큰] CLIP 토크나이저로 general 토큰 수 계산 (기존 코퍼스와 99.96% 일치 확인됨)")
    from transformers import CLIPTokenizerFast

    tok = CLIPTokenizerFast.from_pretrained(CLIP_MODEL)
    texts = out["general"].fillna("").astype(str).tolist()
    counts: list[float] = []
    step = 2000
    for s in range(0, len(texts), step):
        enc = tok(texts[s:s + step])["input_ids"]
        counts.extend(float(len(e)) for e in enc)
    out["tokens"] = counts

    out["image_width"] = merged["image_width"].fillna(0).astype("int64")
    out["image_height"] = merged["image_height"].fillna(0).astype("int64")
    out = out[OUT_COLUMNS]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    new_buckets = []
    for n, start in enumerate(range(0, len(out), BUCKET_ROWS)):
        chunk = out.iloc[start:start + BUCKET_ROWS]
        num = last_bucket + 1 + n
        name = f"tags_{num:03d}.parquet"
        chunk.to_parquet(out_dir / name, index=False, compression="snappy")
        ym = lambda s: str(s)[:7].replace("-", "/")          # noqa: E731
        new_buckets.append({
            "bucket": num, "file": name,
            "min_id": int(chunk["id"].iloc[0]), "max_id": int(chunk["id"].iloc[-1]),
            "rows": int(len(chunk)),
            "start_ym": ym(chunk["created_at"].iloc[0]),
            "end_ym": ym(chunk["created_at"].iloc[-1]),
        })
        print(f"  기록 {name}  {len(chunk):,}행  id {chunk['id'].iloc[0]:,}~{chunk['id'].iloc[-1]:,}")

    if buckets:
        payload = json.loads(BUCKET_INDEX.read_text(encoding="utf-8"))
        payload["buckets"] = buckets + new_buckets
        payload["bucket_count"] = len(payload["buckets"])
        BUCKET_INDEX.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print(f"[인덱스] {BUCKET_INDEX.name} 갱신 — 버킷 {payload['bucket_count']}개")

    print()
    print(f"[완료] 새 버킷 {len(new_buckets)}개 / {len(out):,}행 "
          f"(id {int(out['id'].iloc[0]):,} ~ {int(out['id'].iloc[-1]):,})")
    print(f"⚠️ core/runtime_install_manager.py 의 TAG_ARCHIVE_EXPECTED_COUNT 를 "
          f"{len(buckets) + len(new_buckets) if buckets else 150 + len(new_buckets)} 로 올리고,")
    print("   재배포 zip 은 **이름을 바꿔서** 올리세요(같은 이름은 옛 데이터가 영영 남습니다).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
