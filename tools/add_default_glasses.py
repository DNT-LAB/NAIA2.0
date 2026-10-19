"""안경잡이 캐릭터의 프로필에 `glasses` 를 **특징(기본값)** 으로 넣는다(사용자 기준 2026-10-19).

기준: 프로필 필터(`1girl ∧ solo ∧ ~alternate ∧ ~cosplay`) 그림에서 `glasses` 가 50% 이상이면 안경이 그 캐릭터의
기본값이다. `glasses` 는 `data/clothes_list.txt` 에 있어 의상으로 분류되고, 의상 필드(`key_clothes`)는 배포본에
없어(병합이 버린다) 지금 사전의 어떤 캐릭터에도 안경이 안 붙었다 - 발생: c2-chan(glasses 94.7%).

값(count · pct)은 빌드 산출물에서 가져온다 - `tools/build_character_profile_increment.py --include-known` 으로
만든 `character_analysis_increment.json`(기존 캐릭터까지 담긴다)의 `key_clothes`.

규약(병합 도구와 같다):
  · 이미 `glasses` 가 있는 엔트리는 건드리지 않는다. 그 밖의 필드는 한 글자도 안 바꾼다.
  · 특징 목록은 비율 순서를 유지해 끼워 넣는다.
  · CRLF 를 보존한다(`character_analysis.json` 은 CRLF · 끝에 줄바꿈 없음). 쓰기 전에 `.bak` 을 남긴다.

    python tools/add_default_glasses.py --profile <character_analysis_increment.json>            # dry-run
    python tools/add_default_glasses.py --profile <character_analysis_increment.json> --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = REPO_ROOT / "data" / "character_analysis.json"
NEWLINE = "\r\n"
DEFAULT_GLASSES_PCT = 50.0   # build_character_profile_increment.DEFAULT_GLASSES_PCT 와 같은 값


def glasses_from_build(profile: dict) -> dict[str, dict]:
    """빌드 산출물에서 이름(소문자) -> glasses 항목(count · pct)."""
    found: dict[str, dict] = {}
    for members in profile.values():
        if not isinstance(members, dict):
            continue
        for name, data in members.items():
            if not isinstance(data, dict):
                continue
            pool = list(data.get("key_clothes") or []) + list(data.get("characteristics") or [])
            hit = next((e for e in pool if isinstance(e, dict) and e.get("tag") == "glasses"), None)
            if hit:
                found[name.strip().lower()] = {"tag": "glasses", "count": int(hit.get("count") or 0),
                                               "pct": float(hit.get("pct") or 0)}
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True, type=Path, help="빌드 산출물(--include-known 으로 만든 것)")
    ap.add_argument("--min-pct", type=float, default=DEFAULT_GLASSES_PCT)
    ap.add_argument("--apply", action="store_true", help="실제로 파일을 쓴다")
    args = ap.parse_args()

    analysis = json.loads(ANALYSIS_PATH.read_bytes().decode("utf-8"))
    built = glasses_from_build(json.loads(args.profile.read_text(encoding="utf-8")))
    changed: list[tuple[str, str, float]] = []
    already = 0
    for group, members in analysis.items():
        if group.startswith("_") or not isinstance(members, dict):
            continue
        for name, data in members.items():
            if not isinstance(data, dict):
                continue
            hit = built.get(name.strip().lower())
            if not hit or hit["pct"] < args.min_pct:
                continue
            feats = data.get("characteristics")
            if not isinstance(feats, list):
                feats = data["characteristics"] = []
            if any(isinstance(e, dict) and e.get("tag") == "glasses" for e in feats):
                already += 1
                continue
            at = next((i for i, e in enumerate(feats) if float(e.get("pct") or 0) < hit["pct"]), len(feats))
            feats.insert(at, dict(hit))
            changed.append((name, group, hit["pct"]))
    print(f"glasses >= {args.min_pct:g}% (빌드 기준) -> 특징으로 추가 {len(changed):,}종 · 이미 있음 {already:,}종")
    for name, group, pct in sorted(changed, key=lambda x: -x[2])[:20]:
        print(f"    {pct:5.1f}%  {name}  [{group}]")
    if not args.apply:
        print("\n  [dry-run] 쓰지 않았다 - --apply 로 쓴다")
        return 0
    if not changed:
        return 0
    shutil.copy2(ANALYSIS_PATH, ANALYSIS_PATH.with_suffix(".json.glasses.bak"))
    text = json.dumps(analysis, ensure_ascii=False, indent=2)
    ANALYSIS_PATH.write_bytes(text.replace("\r\n", "\n").replace("\n", NEWLINE).encode("utf-8"))
    print(f"\n  {ANALYSIS_PATH} 갱신 (.json.glasses.bak 보관)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
