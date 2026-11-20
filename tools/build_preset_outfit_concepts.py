"""의상 세트마다 '이 옷차림이면 거의 그 이름의 의상' 을 미리 구워 data/preset_outfit_concepts.json 으로(사용자 11-20).

의상 세트는 부품 태그로만 짰다 - school uniform · serafuku · maid 같은 이름 붙은 옷차림은 세트에 없다.
그래서 벤치 검색 '교복' 이 세일러 칼라 · 네커치프 세트를 못 찾았다. 세트 태그를 모두 단 게시물에서
팩에 없는 옷차림 태그가 얼마나 같이 붙나를 재 두면, 검색어가 그 옷차림을 가리킬 때 그 세트를 찾는다.
('neckerchief, sailor collar, blouse, pleated skirt' = school uniform 95% · serafuku 85%)

근거 = 이벤트 맵 색인(같은 인원 갈래). 런타임에 색인이 없는 사용자도 있어 미리 구워 작은 파일만 싣는다
(data/.claude/BUNDLED_DATA_CLAUDE.md §3).

    python tools/build_preset_outfit_concepts.py --map NAIA-Portable/user-data/data
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

SCHEMA = "naia.preset_outfit_concepts.v1"
PERSONS = {"female": "1girl_solo,1girl", "male": "1boy_solo,1boy"}
# 이름 붙은 옷차림 = 이벤트 맵 갈래 clothing(교복 · 세라복 · 가쿠란 …). 직업 옷차림(maid 등)은 갈래가 cast · body 라
# 이름으로 연다 - cast 를 통째로 열면 male focus · virtual youtuber 가 들어온다(11-20 첫 빌드).
GROUPS = ("clothing",)
EXTRA = ("maid", "butler", "nurse", "miko", "nun", "witch", "cheerleader", "waitress", "police", "idol", "bunny girl",
         "princess", "knight", "ninja", "pirate", "chef", "magical girl", "shrine maiden")
# 옷차림이 아닌 clothing 갈래 태그(구도).
DROP = ("full body", "upper body", "cowboy shot")
# lift 5 = 'long sleeves'(0.72 · 3.3) 같은 흔한 속성은 빠지고 blazer 세트의 school uniform(0.65 · 8.2)은 남는다.
SHARE, LIFT, MIN_POSTS, KEEP = 0.5, 5.0, 50, 4


def build(map_root: Path, pack_path: Path) -> dict:
    service = EventMapService([map_root, ROOT / "data"])
    raw = pack_path.read_bytes()
    rows = json.loads(raw)["sets"]
    vocab = {tag for row in rows for tag in row["tags"]} | {row["seed"] for row in rows}
    sets = {}
    for row in rows:
        result = service.explore(pins=",".join(row["tags"]), persons=PERSONS[row["pool"]], limit=200, sort="posts")
        if int(result.get("observed_posts") or 0) < MIN_POSTS:
            continue
        hits = [(c["tag"], round(float(c["share"]), 3)) for c in result.get("candidates") or []
                if c["tag"] not in vocab and c["tag"] not in DROP and (c.get("group") in GROUPS or c["tag"] in EXTRA)
                and c["share"] >= SHARE and c["lift"] >= LIFT]
        hits.sort(key=lambda hit: -hit[1])
        if hits:
            sets[row["id"]] = [list(hit) for hit in hits[:KEEP]]
    return {
        "schema": SCHEMA,
        "note": "outfit set id -> [named outfit tag, share] (posts with every set tag that also carry it)",
        "rule": {"share": SHARE, "lift": LIFT, "min_posts": MIN_POSTS, "keep": KEEP, "groups": list(GROUPS),
                 "extra": list(EXTRA), "drop": list(DROP), "persons": PERSONS},
        "build": {"built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                  "outfit_presets_sha256": hashlib.sha256(raw).hexdigest()},
        "sets": dict(sorted(sets.items())),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--map", type=Path, required=True, help="event_map/event_map.naiamap 이 든 data 폴더")
    ap.add_argument("--pack", type=Path, default=ROOT / "data/outfit_presets.json")
    ap.add_argument("--out", type=Path, default=ROOT / "data/preset_outfit_concepts.json")
    args = ap.parse_args(argv)
    pack = build(args.map, args.pack)
    args.out.write_text(json.dumps(pack, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    print(f"sets {len(pack['sets'])} -> {args.out}")


if __name__ == "__main__":
    main()
