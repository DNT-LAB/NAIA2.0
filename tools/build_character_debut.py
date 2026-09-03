# -*- coding: utf-8 -*-
"""캐릭터가 태그 코퍼스에 **처음 나타난 달**을 뽑아 도감 옆에 둔다.

왜 미리 만들어 두는가:
  · 코퍼스(`data/tags/*.parquet`, 1.4GB)는 **배포본에 없다** - 사용자가 따로 내려받는
    것이라, 앱이 켜질 때 있다고 가정할 수 없다. 스캔도 8초가 든다(실측).
  · 산출물은 이름 -> "YYYY-MM" 한 줄뿐이라 600KB 남짓이다. 도감 본체
    (`character_analysis.json` 28MB) 옆에 두면 배포 경로가 그대로 같다.

쓰는 곳: 검색 탭의 **[최신] 토글** — "요즘 그려지기 시작한 캐릭터"만 남긴다.

    python tools/build_character_debut.py            # data/ 를 읽고 data/ 에 쓴다
    python tools/build_character_debut.py --since 2024-01
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import time
from collections import Counter
from pathlib import Path

import pandas as pd

# ⚠️ 왼쪽 끝이 잘려 있다. 코퍼스는 2015-12 에서 시작하므로 그 이전에 데뷔한 캐릭터는
#    전부 2015-12 로 뭉친다 - "최신" 을 가리는 데에는 지장이 없다(반대쪽 끝만 본다).
DEFAULT_SINCE = "2025-01"


def _spelling_key(name: str) -> str:
    """철자 흔들림만 뭉갠 열쇠. 작품 괄호는 **그대로 둔다.**

    괄호까지 떼면 `aoba (blue archive)` 와 `aoba (kancolle)` 가 같아져 **다른**
    캐릭터를 개명으로 몰아 버린다(실측: 441건 중 대부분이 그런 오탐이었다).
    """
    base = re.sub(r"[^a-z0-9]+", "", name.lower())
    for long, short in (("ou", "o"), ("uu", "u"), ("oo", "o"), ("ei", "e"), ("aa", "a")):
        base = base.replace(long, short)
    return base


def build(root: Path, since: str, extra: list[str], keep_ratio: float) -> dict:
    files = sorted(glob.glob(str(root / "data" / "tags" / "tags_*.parquet")))
    for folder in extra:
        files.extend(sorted(glob.glob(str(Path(folder) / "tags_*.parquet"))))
    if not files:
        raise SystemExit("코퍼스가 없습니다: data/tags/tags_*.parquet")

    started = time.time()
    first: dict[str, str] = {}
    rows: Counter = Counter()
    for path in files:
        frame = pd.read_parquet(path, columns=["character", "created_at"])
        months = frame["created_at"].astype(str).str.slice(0, 7)
        for names, when in zip(frame["character"].tolist(), months.tolist()):
            if not names:
                continue
            for name in names.split(", "):
                if not name:
                    continue
                rows[name] += 1
                if name not in first or when < first[name]:
                    first[name] = when
    scanned = time.time() - started

    analysis = json.loads((root / "data" / "character_analysis.json").read_text(encoding="utf-8"))
    total: dict[str, int] = {}
    for chars in analysis.values():
        if isinstance(chars, dict):
            for name, data in chars.items():
                if isinstance(data, dict):
                    total[name] = int(data.get("total_rows", 0) or 0)
    known = set(total)

    # ⚠️ **개명을 걷어낸다.** 단부루는 태그 이름을 갈아 끼우고, 코퍼스 버킷은 그때그때의
    #    이름을 담는다 - 그래서 옛 캐릭터가 개명한 달에 '데뷔' 한 것처럼 보인다
    #    (실측: `tamamo no mae (fate)` 2025-01 · 옛 이름은 `tamamo no mae (fate/extra)`).
    #    도감의 `total_rows` 는 **현재 이름 기준 전체**라, 새 이름으로 센 코퍼스 행이
    #    그보다 한참 적으면 나머지는 옛 이름 밑에 있다는 뜻이다.
    #    비교는 **같은 창**에서만 뜻이 있다 - 코퍼스가 도감보다 짧으면 최근 캐릭터가
    #    억울하게 걸린다(증분 버킷을 --extra 로 반드시 함께 넣을 것).
    debut: dict[str, str] = {}
    renamed: list[tuple[float, str]] = []
    for name in sorted(known):
        if name not in first:
            continue
        seen = rows[name]
        want = total.get(name, 0)
        ratio = (seen / want) if want else 1.0
        if first[name] >= since and ratio < keep_ratio:
            renamed.append((ratio, name))
            continue
        debut[name] = first[name]

    # ⚠️ **철자만 바뀐 개명**은 비율로 안 잡힌다 - 도감도 새 이름만 세기 때문이다
    #    (실측: `toph beifong` 코퍼스 460 · 도감 87 -> 비율 5.29 로 멀쩡해 보인다).
    #    같은 작품 안에서 **앞선 쌍둥이**가 있으면 그것이 옛 이름이다.
    twins: dict[str, list[str]] = {}
    for name in first:
        twins.setdefault(_spelling_key(name), []).append(name)
    renamed_twins: list[tuple[str, str]] = []
    for name in list(debut):
        if debut[name] < since:
            continue
        for other in twins.get(_spelling_key(name), []):
            if other != name and first.get(other, "9999") < debut[name]:
                renamed_twins.append((name, other))
                debut.pop(name, None)
                break
    corpus_end = max(first.values()) if first else ""
    years = Counter(value[:4] for value in debut.values())
    recent = sum(1 for value in debut.values() if value >= since)
    print(f"버킷 {len(files)} · 스캔 {scanned:.1f}s · 코퍼스 캐릭터 {len(first):,}")
    print(f"도감 {len(known):,} · 데뷔 확인 {len(debut):,} · 코퍼스 끝 {corpus_end}")
    print(f"연도 분포: {dict(sorted(years.items()))}")
    print(f"{since} 이후 데뷔: {recent:,}")
    print(f"개명으로 걷어낸 것: 행수 {len(renamed):,} (코퍼스/도감 < {keep_ratio})"
          f" · 철자 {len(renamed_twins):,}")
    for ratio, name in sorted(renamed)[:4]:
        print(f"    {ratio:5.2f}  {name}")
    for name, other in renamed_twins[:4]:
        print(f"    철자  {name}  <- {other}")
    return {
        "version": 1,
        "corpus_buckets": len(files),
        "corpus_end": corpus_end,
        "recent_since": since,
        "renamed_dropped": len(renamed) + len(renamed_twins),
        "debut": debut,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--extra", action="append", default=[],
                        help="추가 버킷 폴더(증분). 여러 번 줄 수 있다")
    parser.add_argument("--keep-ratio", type=float, default=0.25,
                        help="코퍼스/도감 행 비가 이보다 낮으면 개명으로 보고 뺀다")
    parser.add_argument("--since", default=DEFAULT_SINCE,
                        help="[최신] 토글이 남길 데뷔 하한 (YYYY-MM)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    payload = build(root, args.since, args.extra, args.keep_ratio)
    out = root / "data" / "character_debut.json"
    # ⚠️ `write_text` 는 Windows 에서 개행을 CRLF 로 바꾼다 - newline 을 못 박는다.
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"기록: {out} ({out.stat().st_size / 1024:.0f}KB)")


if __name__ == "__main__":
    main()
