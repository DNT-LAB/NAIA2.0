# -*- coding: utf-8 -*-
"""인원 그룹별 조합 모델을 굽는다 -> `data/tag_combo/<group>.ncsr`.

## 근거

설계와 실측은 `tools/reco_probe/SPEC.md`. 핵심만:

  - 원천은 `data/tags/*.parquet` 다. Quick Search 의 `.tgp` 는 빌드 시점에
    의상/특징/배경 어휘가 통째로 빠져 있어(`metadata.tgpm` 의 `filters_removed`)
    조합 추천에 못 쓴다.
  - 그룹당 게시물 상한을 둔다. `1girl_solo` 는 393만 건이지만 73.1만 -> 145.5만으로
    두 배 늘려도 지표가 0.143 -> 0.144 다. 상한 없이 담으면 771MB 가 된다.
  - 어휘 문턱을 올려도 메모리는 안 줄어든다(희귀 태그 기여 0.14%). 줄이는 수단은
    게시물 표본추출뿐이다.

## 쓰는 법

    python tools/build_tag_combo_models.py --dry-run
    python tools/build_tag_combo_models.py --cap 800000
    python tools/build_tag_combo_models.py --only 1girl_solo
"""
from __future__ import annotations

import argparse
import hashlib
import random
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tag_combo.model import MAX_LOCAL_VOCAB, write_model   # noqa: E402
from core.tag_combo.person import PERSON_GROUPS, person_group_of  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHARD_DIR = ROOT / "data" / "tags"
OUT_DIR = ROOT / "data" / "tag_combo"
RATING_ID = {"g": 0, "s": 1, "q": 2, "e": 3}


def main() -> int:
    ap = argparse.ArgumentParser(description="인원 그룹별 조합 모델 빌드")
    ap.add_argument("--cap", type=int, default=800_000,
                    help="그룹당 게시물 상한. 0 = 무제한(전 코퍼스). "
                         "80만 표본은 흔한 태그에는 충분하지만 희귀 태그를 "
                         "구조적으로 잘라낸다 - 실측으로 축 어휘 중 앵커가 되는 "
                         "비율이 51.7%%(표본) vs 81.2%%(전량)다")
    ap.add_argument("--min-freq", type=int, default=20,
                    help="그룹 안에서 이만큼은 나와야 어휘에 넣는다")
    ap.add_argument("--only", default="", help="이 그룹만 만든다")
    ap.add_argument("--seed", type=int, default=20260814)
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 통계만")
    args = ap.parse_args()

    shards = sorted(SHARD_DIR.glob("tags_*.parquet"),
                    key=lambda p: int(p.stem.split("_")[1]))
    if not shards:
        print(f"!! 샤드가 없다: {SHARD_DIR}")
        return 2
    want = {args.only} if args.only else set(PERSON_GROUPS)
    bad = want - set(PERSON_GROUPS)
    if bad:
        print(f"!! 모르는 그룹: {sorted(bad)}")
        return 2

    if args.cap < 0:
        # 도움말은 `0 = 무제한` 인데 음수도 무제한으로 처리하고 있었다 - 오타가
        # 조용히 전 코퍼스 빌드가 된다(Codex 지적).
        print(f"!! --cap 은 0(무제한) 이상이어야 한다: {args.cap}")
        return 2
    cap = args.cap if args.cap > 0 else None
    print(f"샤드 {len(shards)}개 / 대상 그룹 {len(want)}개 / "
          f"상한 {'무제한' if cap is None else f'{cap:,}'}")
    t0 = time.time()
    # 저장통. 상한을 넘으면 reservoir 로 바꿔 담아 메모리를 묶는다.
    docs: dict[str, list[tuple[frozenset, int, str]]] = {g: [] for g in want}
    seen: Counter = Counter()
    rng = random.Random(args.seed)
    # **태그 문자열을 공유한다.** `g.split()` 은 행마다 새 str 을 만든다. 전
    # 코퍼스(750만 행 x 태그 22개)면 같은 문자열 1억 6천만 개가 따로 살아 있어
    # 수 GB 를 날린다 - 어휘는 1만 5천 종뿐이므로 재사용하면 그만이다.
    pool: dict[str, str] = {}
    for n, p in enumerate(shards, 1):
        tb = pq.read_table(p, columns=["general", "rating", "character"])
        gs = tb.column("general").to_pylist()
        rs = tb.column("rating").to_pylist()
        cs = tb.column("character").to_pylist()
        for g, r, c in zip(gs, rs, cs):
            if not g:
                continue
            s = frozenset(pool.setdefault(x, x) for x in g.split(", "))
            grp = person_group_of(s)
            if grp not in want:
                continue
            seen[grp] += 1
            rec = (s, RATING_ID.get(r or "", 1), (c or "").split(", ")[0])
            bucket = docs[grp]
            if cap is None or len(bucket) < cap:
                bucket.append(rec)
            else:
                # reservoir - 시대 편향 없이 균일 표본
                j = rng.randrange(seen[grp])
                if j < cap:
                    bucket[j] = rec
        if n % 30 == 0:
            print(f"  {n}/{len(shards)}  {time.time()-t0:.0f}s", flush=True)
    print(f"스캔 {time.time()-t0:.0f}s")

    src_hash = hashlib.sha256(
        "".join(f"{p.name}:{p.stat().st_size}" for p in shards).encode()
    ).hexdigest()[:16]

    print(f"\n{'group':<30}{'전체':>10}{'표본':>10}{'어휘':>8}{'nnz':>12}{'MB':>7}")
    total_mb = 0.0
    for grp in PERSON_GROUPS:
        if grp not in want:
            continue
        bucket = docs[grp]
        if not bucket:
            print(f"{grp:<30}{seen[grp]:>10,}   (게시물 없음)")
            continue
        freq: Counter = Counter()
        for s, _, _ in bucket:
            freq.update(s)
        tags = [t for t, c in freq.most_common() if c >= args.min_freq]
        if len(tags) > MAX_LOCAL_VOCAB:
            print(f"!! {grp}: 어휘 {len(tags):,} 가 uint16 상한을 넘는다")
            return 1
        tid = {t: i for i, t in enumerate(tags)}
        char_id: dict[str, int] = {}
        rows, post_rating, post_char = [], [], []
        tag_rating = np.zeros((len(tags), 4), dtype=np.uint32)
        for s, r, ch in bucket:
            ids = sorted(tid[t] for t in s if t in tid)
            rows.append(ids)
            post_rating.append(r)
            if ch:
                post_char.append(char_id.setdefault(ch, len(char_id) + 1))
            else:
                post_char.append(0)
            for i in ids:
                tag_rating[i, r] += 1
        nnz = sum(len(r) for r in rows)
        mb = (nnz * 2 + (len(rows) + 1) * 8 + len(rows) * 5 + len(tags) * 16) / 1e6
        total_mb += mb
        print(f"{grp:<30}{seen[grp]:>10,}{len(rows):>10,}{len(tags):>8,}"
              f"{nnz:>12,}{mb:>7.0f}")
        if args.dry_run:
            continue
        meta = write_model(
            OUT_DIR / f"{grp}.ncsr", group=grp, rows=rows, tags=tags,
            freq=[int(freq[t]) for t in tags], post_rating=post_rating,
            post_char=post_char, tag_rating=tag_rating,
            sampled_from=seen[grp], source_hash=src_hash)
        del meta
    print(f"{'합계':<30}{sum(seen.values()):>10,}{'':>10}{'':>8}{'':>12}{total_mb:>7.0f}")
    if args.dry_run:
        print("\n--dry-run: 쓰지 않았습니다.")
    else:
        print(f"\n저장: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
