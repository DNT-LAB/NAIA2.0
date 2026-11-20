"""자세 · 2인 자세 세트마다 '거의 늘 함께 나오는 몸 태그' 를 미리 구워 data/preset_cooccur.json 으로(사용자 11-20).

세트 빌더는 동작 · 자세 어휘만 모으므로 그 동작에 꼭 있어야 할 몸(penis 등)이 세트에 없다 -
"looking at penis, precum" 을 단 1girl 1boy 게시물의 97% 에 penis 가 있지만 세트에는 없다.
벤치는 이 표의 태그를 세트와 함께 메인 프롬프트에 싣는다.

근거 = 이벤트 맵 색인(같은 인원 갈래에서 세트 태그를 모두 단 게시물). 런타임에 색인이 없는 사용자도 있어
미리 구워 작은 파일만 싣는다(data/.claude/BUNDLED_DATA_CLAUDE.md §3).

    python tools/build_preset_cooccur.py --map NAIA-Portable/user-data/data
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.event_map.service import EventMapService  # noqa: E402

SCHEMA = "naia.preset_cooccur.v1"
# 세트 풀 -> 이벤트 맵 인원 갈래(세트 빌더의 코퍼스 갈래와 같은 뜻).
PERSONS = {"female": "1girl_solo,1girl", "male": "1boy_solo,1boy", "girl_boy": "1girl_1boy",
           "girl_girl": "2girls", "boy_boy": "2boys"}
# 그 동작에 꼭 그려져야 할 몸 · 상대. 캐릭터의 생김새 · 종을 바꾸는 태그(muscular · furry · futanari · large pectorals)와
# 넓은 말(cum · sex · holding · weapon - 세트에 더 좁은 태그가 이미 있다)은 넣지 않는다(사용자 11-20 '몸 태그만').
ALLOW = ("penis", "testicles", "erection", "pussy", "nipples", "ass", "anus", "pectorals", "feet", "toes",
         "armpits", "bulge", "tentacles")
SHARE, LIFT, MIN_POSTS = 0.9, 3.0, 50
FAMILIES = ("event", "link")      # 메인 프롬프트로 가는 갈래(1인 자세 · 2인 자세)


def build(map_root: Path, pack_path: Path) -> dict:
    # 색인 폴더 + 저장소 data(대분류 표 KR_tags 등) - 앱의 default_roots 와 같은 차례.
    service = EventMapService([map_root, ROOT / "data"])
    raw = pack_path.read_bytes()
    sets = {}
    for row in json.loads(raw)["sets"]:
        if row["family"] not in FAMILIES:
            continue
        result = service.explore(pins=",".join(row["tags"]), persons=PERSONS[row["pool"]], limit=60, sort="posts")
        if int(result.get("observed_posts") or 0) < MIN_POSTS:
            continue
        tags = [c["tag"] for c in result.get("candidates") or []
                if c["tag"] in ALLOW and c["tag"] not in row["tags"] and c["share"] >= SHARE and c["lift"] >= LIFT]
        if tags:
            sets[row["id"]] = tags
    return {
        "schema": SCHEMA,
        "note": "set id -> body tags that almost always co-occur with the set (added to the bench main prompt)",
        "rule": {"share": SHARE, "lift": LIFT, "min_posts": MIN_POSTS, "allow": list(ALLOW),
                 "families": list(FAMILIES), "persons": PERSONS},
        "build": {"built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                  "event_presets_sha256": hashlib.sha256(raw).hexdigest()},
        "sets": dict(sorted(sets.items())),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--map", type=Path, required=True, help="event_map/event_map.naiamap 이 든 data 폴더")
    ap.add_argument("--pack", type=Path, default=ROOT / "data/event_presets.json")
    ap.add_argument("--out", type=Path, default=ROOT / "data/preset_cooccur.json")
    args = ap.parse_args(argv)
    pack = build(args.map, args.pack)
    args.out.write_text(json.dumps(pack, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    print(f"sets {len(pack['sets'])} -> {args.out}")


if __name__ == "__main__":
    main()
