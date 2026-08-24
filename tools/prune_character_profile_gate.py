#!/usr/bin/env python3
"""캐릭터 프로필의 퍼센트 문턱을 사후에 적용한다(가지치기 + 검사).

## 왜 필요한가

`data/character_analysis.json` 의 본 프로필을 만든 원본 빌더
(`tools/character_profile/analyze_characters.py`)에는 **퍼센트 문턱이 없다.**
버킷당 `top_n` 개수 상한만 있다:

    if tag in classify["personal_color"]:
        if len(result["personal_color"]) < top_n:      # <- 개수만 본다
            result["personal_color"].append(entry)

`most_common()` 은 내림차순이라 상한에 걸리기 전까지 **0.3% 짜리도 다 담긴다.**
그래서 `lacrimosa (nte)` (129행)의 색이 15종까지 늘어났다 - `multicolored hair 94.6%`
옆에 `red hair 0.8%`(1장)가 나란히 붙는다. 소비자가 그 목록을 그대로 쓰기 때문에
(`character_viewer_service.py` 의 캐릭터 프롬프트 조립에는 자체 문턱이 없다)
프롬프트에도 통째로 들어간다. 사용자 제보 2026-08-24.

증분 빌더(`tools/build_character_profile_increment.py`)는 이미 문턱을 건다. 실측으로
확인했다 - 증분이 넣은 +393, +1,214 종은 **미달 0건**이고, 미달 2,875종은 전부
증분 이전부터 있던 것이다. 그래서 고칠 곳은 빌더가 아니라 **이미 배포된 값**이다.

## 왜 재계산이 아니라 가지치기인가

파일이 `count` 와 `pct` 를 이미 들고 있어 문턱은 **순수한 부분집합 연산**이다.
원천 parquet(295MB, 이 리포에 없음)을 다시 돌 이유가 없다.

⚠️ 순서가 문제되지 않는다는 것도 실측했다. `top_n` 상한에 닿은 캐릭터는
   색 0명 / 특징 21명이고, 문턱을 건 뒤 30종에 다시 닿는 캐릭터는 0명이다.
   즉 "문턱→상한" 과 "상한→문턱" 이 같은 답을 준다.

## 문턱 값

증분 빌더의 기본값과 **같은 값**을 쓴다(색 30% · 특징 20%). 지금 데이터가 그 값을
뒷받침한다 - 색의 최저 pct 분포가 30% 에서 갈린다(30% 미만 15.8% · 40% 미만 36.2%).
두 값 모두 소비자의 자체 문턱보다 낮아(정보 카드 50%, `build_character_wildcards.py`
40/50, `build_character_presets.mjs` 50) 화면을 굶기지 않는다.

## variant(alternates)는 기본적으로 건드리지 않는다

변형에는 문턱이 **이미 있다** - `add_alternate_costumes.py` 의 `MIN_PCT = 10.0` /
`MIN_CLOTHES_PCT = 15.0`. 없는 게 아니라 느슨한 것이고, 변형은 표본이 작아
(행 수 중위 16) 원저자가 일부러 낮춰 둔 값이다. 본 프로필과 같은 잣대로 올리는 것은
버그 수정이 아니라 **판단**이라 `--variants` 로 명시할 때만 한다.

## 사용

    python tools/prune_character_profile_gate.py --check      # 검사만(위반 시 exit 1)
    python tools/prune_character_profile_gate.py --dry-run    # 무엇이 지워지는지 보기
    python tools/prune_character_profile_gate.py              # 실제 가지치기
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 증분 빌더(`build_character_profile_increment.py`)의 기본값과 같은 값이어야 한다.
# 둘이 어긋나면 증분이 넣은 값과 기존 값의 잣대가 달라진다.
MIN_PCT_COLOR = 30.0
MIN_PCT_CHAR = 20.0

DEFAULT_DATA = Path("data") / "character_analysis.json"


def _gate(entries, floor: float) -> tuple[list, list]:
    """(남길 것, 버릴 것). 엔트리가 dict 가 아니면 판단하지 않고 남긴다."""
    keep, drop = [], []
    for entry in entries or []:
        if not isinstance(entry, dict):
            keep.append(entry)
            continue
        (drop if float(entry.get("pct", 0) or 0) < floor else keep).append(entry)
    return keep, drop


class Report:
    def __init__(self) -> None:
        self.characters = 0
        self.hit_characters = 0
        self.dropped_color = 0
        self.dropped_char = 0
        self.emptied_color = 0
        self.emptied_char = 0
        self.variants = 0
        self.hit_variants = 0
        self.dropped_variant = 0
        self.samples: list[str] = []


def prune(data: dict, *, min_color: float, min_char: float,
          do_variants: bool, apply: bool) -> Report:
    rep = Report()
    for group, chars in data.items():
        if not isinstance(chars, dict):
            continue
        for name, info in chars.items():
            if not isinstance(info, dict):
                continue
            rep.characters += 1
            keep_pc, drop_pc = _gate(info.get("personal_color"), min_color)
            keep_ch, drop_ch = _gate(info.get("characteristics"), min_char)
            if drop_pc or drop_ch:
                rep.hit_characters += 1
                rep.dropped_color += len(drop_pc)
                rep.dropped_char += len(drop_ch)
                if info.get("personal_color") and not keep_pc:
                    rep.emptied_color += 1
                if info.get("characteristics") and not keep_ch:
                    rep.emptied_char += 1
                if len(rep.samples) < 8:
                    worst = ", ".join(
                        f"{e['tag']} {e['pct']}%"
                        for e in sorted(drop_pc + drop_ch,
                                        key=lambda e: e.get("pct", 0))[:3])
                    rep.samples.append(
                        f"{name} [{group}] rows={info.get('total_rows', 0)}"
                        f" -{len(drop_pc)}색 -{len(drop_ch)}특징  ({worst})")
                if apply:
                    info["personal_color"] = keep_pc
                    info["characteristics"] = keep_ch

            for variant in info.get("alternates") or []:
                if not isinstance(variant, dict):
                    continue
                rep.variants += 1
                if not do_variants:
                    continue
                v_pc, v_drop_pc = _gate(variant.get("personal_color"), min_color)
                v_ch, v_drop_ch = _gate(variant.get("characteristics"), min_char)
                if v_drop_pc or v_drop_ch:
                    rep.hit_variants += 1
                    rep.dropped_variant += len(v_drop_pc) + len(v_drop_ch)
                    if apply:
                        variant["personal_color"] = v_pc
                        variant["characteristics"] = v_ch
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--min-pct-color", type=float, default=MIN_PCT_COLOR)
    ap.add_argument("--min-pct-char", type=float, default=MIN_PCT_CHAR)
    ap.add_argument("--variants", action="store_true",
                    help="변형(alternates)에도 같은 문턱을 건다. 변형에는 이미 10%%/15%% "
                         "문턱이 있어 기본은 건드리지 않는다")
    ap.add_argument("--check", action="store_true",
                    help="쓰지 않고 검사만. 위반이 하나라도 있으면 exit 1")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 보고만")
    args = ap.parse_args()

    if not args.data.exists():
        print(f"ERROR: not found: {args.data}")
        return 2

    data = json.loads(args.data.read_text(encoding="utf-8"))
    apply = not (args.check or args.dry_run)
    rep = prune(data, min_color=args.min_pct_color, min_char=args.min_pct_char,
                do_variants=args.variants or args.check, apply=apply)

    print(f"[data] {args.data}  characters={rep.characters:,}  variants={rep.variants:,}")
    print(f"[gate] color >= {args.min_pct_color}%  characteristics >= {args.min_pct_char}%")
    print(f"[main] below gate: {rep.hit_characters:,} characters"
          f"  (-{rep.dropped_color:,} color, -{rep.dropped_char:,} characteristics)")
    print(f"       emptied: {rep.emptied_color:,} color lists, {rep.emptied_char:,} characteristics lists")
    if args.variants or args.check:
        print(f"[variant] below gate: {rep.hit_variants:,} variants (-{rep.dropped_variant:,} entries)")
    for line in rep.samples:
        print("   " + line)

    if args.check:
        # 검사에서는 본 프로필만 실패 조건이다. 변형은 자체 문턱(10%/15%)이 따로 있어
        # 여기서 실패시키면 정상 상태를 계속 빨갛게 만든다 - 숫자만 보고한다.
        if rep.hit_characters:
            print(f"FAIL: {rep.hit_characters:,} characters carry sub-gate entries")
            return 1
        print("OK: no sub-gate entries in main profiles")
        return 0

    if args.dry_run:
        print("(dry-run: nothing written)")
        return 0

    # 원본과 같은 직렬화. 형식이 어긋나면 39MB 파일이 통째로 diff 에 떠서 실제 변경이
    # 묻힌다. ⚠️ **CRLF 이고 끝에 줄바꿈이 없다** - 무변경 라운드트립이 바이트 단위로
    # 같은 것을 확인하고 정한 조합이다(LF 로 쓰면 1,784,960 바이트가 어긋난다).
    body = json.dumps(data, ensure_ascii=True, indent=2).replace("\n", "\r\n")
    args.data.write_bytes(body.encode("utf-8"))
    print(f"[written] {args.data}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
