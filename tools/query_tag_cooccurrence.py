# -*- coding: utf-8 -*-
"""태그 공기(co-occurrence) 직접 쿼리 — 인원 판정의 최종 근거.

## 왜 필요한가

이벤트 프리셋 파티션(`data/interactive_preset_facts.json`)이 인원 실측을 주지만
커버리지가 86%다. 나머지와, 프리셋 집계가 애매한 태그(`cheek pinching` 처럼
자기 볼인지 남의 볼인지 갈리는 것)는 **원본 데이터에 직접 물어보는 편이 낫다.**

## 비용 제한

`data/tags/tags_*.parquet` 은 150개 샤드다. 전량 스캔은 비싸므로 기본값은
**최신 10개**(`tags_140`~`149`, 약 65만 건)로 제한한다. 사용자 지침:
"검색 시스템은 비용이 비싸므로 최신 10개 parquet으로 한정하여 쿼리".

10개 샤드로도 고빈도 태그는 수천 건이 잡히고, 비율 판정에는 그걸로 충분하다.
표본이 30건 미만이면 비율을 믿지 않고 `insufficient` 로 낸다.

## 쓰는 법

    python tools/query_tag_cooccurrence.py "cheek pinching" "hands in hair"
    python tools/query_tag_cooccurrence.py --file 태그목록.txt --shards 20
"""
from __future__ import annotations

import argparse
import glob
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

TAG_DIR = Path("data/tags")
# 인원 구성 마커. Danbooru 는 인물 수를 이 태그들로 표기한다.
SOLO_MARK = "solo"
MULTI_MARKS = ("2girls", "3girls", "4girls", "5girls", "6+girls", "multiple girls",
               "2boys", "3boys", "4boys", "5boys", "6+boys", "multiple boys",
               "multiple others")
MIN_SAMPLE = 30


def shard_paths(n: int) -> list[Path]:
    fs = sorted(glob.glob(str(TAG_DIR / "tags_*.parquet")),
                key=lambda p: int(Path(p).stem.split("_")[-1]))
    return [Path(p) for p in fs[-n:]]


def scan(tags: list[str], shards: int) -> dict[str, dict]:
    want = {t.strip().lower() for t in tags if t.strip()}
    stat = {t: {"posts": 0, "solo": 0, "multi": 0, "partners": Counter()} for t in want}
    paths = shard_paths(shards)
    total_rows = 0
    for p in paths:
        df = pd.read_parquet(p, columns=["general"])
        for cell in df["general"]:
            if not cell:
                continue
            total_rows += 1
            # 셀은 쉼표로 이어진 태그 문자열이다.
            row = {x.strip() for x in str(cell).split(",") if x.strip()}
            hit = want & row
            if not hit:
                continue
            is_solo = SOLO_MARK in row
            is_multi = any(m in row for m in MULTI_MARKS)
            for t in hit:
                s = stat[t]
                s["posts"] += 1
                if is_solo and not is_multi:
                    s["solo"] += 1
                elif is_multi:
                    s["multi"] += 1
    for t, s in stat.items():
        known = s["solo"] + s["multi"]
        s["known"] = known
        s["share"] = round(s["solo"] / known, 4) if known else None
        s["verdict"] = ("insufficient" if known < MIN_SAMPLE
                        else "MULTI" if s["share"] < 0.20
                        else "SOLO" if s["share"] >= 0.30 else "BOTH")
        s.pop("partners", None)
    return {"_rows": total_rows, "_shards": [p.name for p in paths], **stat}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="태그 인원 공기 쿼리 (최신 샤드 한정)")
    ap.add_argument("tags", nargs="*")
    ap.add_argument("--file", help="태그 목록 파일(한 줄에 하나)")
    ap.add_argument("--shards", type=int, default=10, help="최신 샤드 개수 (기본 10)")
    a = ap.parse_args(argv)

    tags = list(a.tags)
    if a.file:
        tags += [l.strip() for l in Path(a.file).read_text(encoding="utf-8").splitlines()
                 if l.strip()]
    if not tags:
        ap.print_help()
        return 1

    res = scan(tags, a.shards)
    print(f"샤드 {len(res['_shards'])}개 / {res['_rows']:,}건 스캔 "
          f"({res['_shards'][0]} ~ {res['_shards'][-1]})\n")
    print(f"{'태그':30s} {'등장':>7s} {'solo':>7s} {'multi':>7s} {'solo비':>7s}  판정")
    for t in sorted(k for k in res if not k.startswith("_")):
        s = res[t]
        sh = f"{s['share']:.3f}" if s["share"] is not None else "  -  "
        print(f"{t:30s} {s['posts']:>7,} {s['solo']:>7,} {s['multi']:>7,} {sh:>7s}  "
              f"{s['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
