# -*- coding: utf-8 -*-
"""3단 지도 초안 -> 런타임 지도 파일 `core/event_map/tree_3depth.json`(배포판에 실린다 - core/** 이 실린다).

사용법
    python tools/export_event_map_tree.py ^
        --draft data/danbooru_wiki_snapshot/event_map_3depth_draft_20261014.json ^
        --out core/event_map/tree_3depth.json --version 2026-10-14

초안은 `tools/build_event_map_3depth_draft.py` 가 굽는다(원재료 · 정리 명세 · 살리기 · 이름표).
런타임 파일에는 **이름과 계층만** 싣는다 - 위키 본문 · 원문 제목 · 빌드 경로 같은 것은 싣지 않는다.
태그 순서는 관측이 많은 순(화면은 어차피 고른 인원 · 등급에서 다시 줄 세운다).

내보내기 전에 두 가지를 확인하고 하나라도 걸리면 쓰지 않는다:
  * 색상 태그가 없다(맵과 같은 함수 `core.event_map.policy.color_exclusion_reason`).
  * 연령 위험 어휘(`tools/thumb_age_guard.py` DANGER_AGE_RE)가 허용 목록(패션 · 란제리 이름) 밖에 없다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.event_map.policy import color_exclusion_reason  # noqa: E402
from core.event_map.tree import SCHEMA, EventMapTree  # noqa: E402
import thumb_age_guard  # noqa: E402

# 연령 판정 정규식이 잡지만 연령과 무관한 이름(패션 양식 · 란제리). 2026-10-14 전수 확인.
AGE_REGEX_FALSE_POSITIVES = {"lolita fashion", "gothic lolita", "sweet lolita", "classic lolita", "babydoll"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--version", required=True)
    args = ap.parse_args()
    draft = json.loads(args.draft.read_text(encoding="utf-8"))
    out = {"schema": SCHEMA, "version": args.version,
           "about": "NAIA 이벤트 맵 3단 지도. Danbooru 위키 tag_groups 를 이벤트 맵 취지에 맞게 다듬었다. "
                    "이름 · 계층은 NAIA 가 새로 지었다.",
           "d1": []}
    tags_all, bad_color, bad_age = set(), [], []
    for d1 in draft["d1"]:
        o1 = {"id": d1["id"], "ko": d1["label_ko"], "d2": []}
        for d2 in d1["d2"]:
            o2 = {"id": d2["id"], "ko": d2["label_ko"], "d3": []}
            for d3 in d2["d3"]:
                tags = [t["tag"] for t in sorted(d3["tags"], key=lambda t: -t["obs"])]
                for t in tags:
                    tags_all.add(t)
                    if color_exclusion_reason(t):
                        bad_color.append(t)
                    if thumb_age_guard.DANGER_AGE_RE.search(t) and t not in AGE_REGEX_FALSE_POSITIVES:
                        bad_age.append(t)
                o2["d3"].append({"id": d3["id"], "ko": d3["label_ko"], "tags": tags})
            o1["d2"].append(o2)
        out["d1"].append(o1)
    if bad_color or bad_age:
        print("refused: color", sorted(set(bad_color))[:20], "age", sorted(set(bad_age))[:20])
        return 1
    EventMapTree(out)  # 계약 확인(겹치는 id · 빈 절)
    args.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n",
                        encoding="utf-8", newline="\n")
    n2 = sum(len(d1["d2"]) for d1 in out["d1"])
    n3 = sum(len(d2["d3"]) for d1 in out["d1"] for d2 in d1["d2"])
    print(f"{args.out} {args.out.stat().st_size:,} B · d1 {len(out['d1'])} · d2 {n2} · d3 {n3} · tags {len(tags_all):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
