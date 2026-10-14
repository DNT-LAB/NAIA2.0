# -*- coding: utf-8 -*-
"""이벤트 맵 3단 지도 초안 - Danbooru tag_groups 트리 + Codex 의견 + 사용자 결정 -> D1 > D2 > D3 > 태그.

사용법
    python tools/build_event_map_3depth_draft.py ^
        --tree data/danbooru_wiki_snapshot/tag_group_tree.json ^
        --codex data/danbooru_wiki_snapshot/codex_orphans_20261014 ^
        --decisions data/danbooru_wiki_snapshot/user_decisions_20261014.tsv ^
        --map C:\\VNR\\DEV\\NAIA-Event-Map-Build\\full-min5-20260912\\event_map.naiamap ^
        --related data/danbooru_wiki_snapshot/codex_related_20261014/related_placements.tsv ^
        --out data/danbooru_wiki_snapshot/event_map_3depth_draft_20261014.json

단 (사용자 결정 2026-10-14)
    D1  위키 `tag_groups` 의 Visual 갈래 10개(루트의 h6). Metatags · 작품 목록은 넣지 않는다.
    D2  그룹 쪽. 루트의 글머리표 중첩(Body parts > Face tags > Eyes tags)은 펴서 형제로 둔다.
        두 갈래에 걸린 쪽(neck_and_neckwear · eyewear)은 처음 나온 갈래에 두고 `also_in` 에 적는다.
        + Objects 아래 새 쪽 `naia:everyday_objects`(일상 사물) - 위키에 없는 자리.
    D3  쪽 안의 첫 단 제목. **태그가 120개를 넘고 하위 제목이 있으면 하위 제목을 D3 로 올린다**
        (`Fetishes · Exhibitionism, …`). 하위 제목 앞에 바로 달린 태그는 첫 단 이름의 D3 에 남는다.
    잎  맵 어휘에 있는 태그만. 색상은 버린다(맵과 같은 함수). `… (cosplay)` 캐릭터 태그도 버린다.
        guarded · nonvisual 갈래는 넣지 않는다.
    이름  갈래 · 그룹 · 절은 한국어 이름을 단다(`tools/event_map_3depth_labels_ko.json`). 태그는 번역하지 않는다.
          표에 없는 이름은 영어 그대로 두고 stats.missing_labels 에 적는다.

태그가 자리를 얻는 길(`via`) - 먼저 걸린 것
    direct     그룹 쪽에 그대로 나온다(general · adult · unclassified 갈래)
    implied    함의 위로(`pleated skirt` -> skirt 의 자리) · children 함의 자식의 자리 · wiki_ref 위키 본문이 가리킨 쪽
    codex      미분류를 Codex 가 놓은 자리(place · new_section)
    user       사용자 결정(`--decisions`) - Codex 보다 앞선다
    objects    Codex 가 보류한 일상 사물을 이 스크립트의 명단으로 일상 사물 쪽에 놓은 것
    한 태그가 여러 자리에 있어도 된다(위키도 그렇게 한다).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.event_map.pack import PackReader  # noqa: E402
from core.event_map.policy import color_exclusion_reason  # noqa: E402

SPLIT_OVER = 120
LANES_DIRECT = {"general", "adult", "unclassified"}
INTRO = "(intro)"
OBJ = "naia:everyday_objects"


# Codex 의 새 절 중 일상 사물 쪽으로 옮기는 것 (사용자 결정 2026-10-14). (원래 D2, 새 절 이름) -> 일상 사물의 D3
MOVE_TO_OBJECTS = {
    ("tag_group:locations", "Furniture and architectural details"): "Furniture and fixtures",
    ("list_of_game_activities", "Toys and play objects"): "Toys and play objects",
    ("tag_group:technology", "Household appliances"): "Household appliances",
    ("tag_group:technology", "Clocks and timekeeping"): "Clocks and timekeeping",
    ("tag_group:technology", "Photography and video devices"): "Photography and video devices",
    ("tag_group:technology", "Scientific instruments"): "Scientific instruments",
}
# 기존 절이 이미 있는데 Codex 가 새 절을 만든 것 -> 기존 절로 합친다.
MERGE_INTO_EXISTING = {
    ("tag_group:accessories", "Bags and carriers"): "Bags",
}

# Codex 가 flag 로 남긴 일상 사물. 위키 정의를 읽고 손으로 고른 명단이다(상위 2,700 안의 보류 189개에서).
OBJECT_LISTS = {
    "Books, stationery and art supplies": """
open book|clipboard|book stack|calligraphy brush|map|map (object)|eraser|love letter|mechanical pencil|
paper stack|bookmark|sticky note|nib pen (object)|papers|inkwell|note|wax seal|paperclip|crumpled paper|
board eraser|pile of books|binder|postage stamp|colored pencil|bible (object)|globe|canvas (object)|easel|
art brush|paint tube|paint can|spray paint|spray can|giant brush""",
    "Containers and boxes": """
cardboard box|tissue box|barrel|birdcage|treasure chest|crate|drum (container)|carton|wooden box|open box|
canister|donation box|laundry basket|trash bag|flask|round-bottom flask|erlenmeyer flask|beaker|
soap bottle|shampoo bottle""",
    "Household and hygiene goods": """
used tissue|soap|toilet paper|toothpaste|cotton swab|mimikaki|bamboo broom|feather duster|rag|clothes pin|
trash|duct tape|caution tape|sewing needle|needle|knitting needle|spool|pin|net|mousetrap|bear trap|lasso|
pacifier""",
    "Money and valuables": """
banknote|holed coin|coin on string|dollar bill|treasure""",
}
# 위키가 '쓰지 마라' 고 적은 태그 - 지도에 두지 않는다.
# 캐릭터 코스프레 태그(`hatsune miku (cosplay)`)는 버린다(사용자 결정 2026-10-14). 맨 `cosplay` 는 남는다.
COSPLAY_RE = re.compile(r"\(cosplay\)$")
DO_NOT_USE_RE = re.compile(r"^(ambiguous|deprecated|use a more specific|use one of|do not use|see\b)", re.I)


def read_tsv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE))


def space(tag: str) -> str:
    return tag.replace("_", " ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True, type=Path)
    ap.add_argument("--codex", required=True, type=Path)
    ap.add_argument("--decisions", required=True, type=Path)
    ap.add_argument("--map", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--related", type=Path, default=None,
                    help="`Related` 칸 태그의 절 배치(Codex related_placements.tsv). 없으면 쪽의 `Related` 칸에 남는다")
    ap.add_argument("--labels-ko", type=Path, default=Path(__file__).with_name("event_map_3depth_labels_ko.json"))
    ap.add_argument("--prune", type=Path, default=None,
                    help="정리 명세(tools/event_map_3depth_prune.json). 없으면 정리하지 않는다")
    ap.add_argument("--rescue", type=Path, default=None,
                    help="정리로 사라질 태그 중 살릴 것(tag, d2, d3 = 절 id) TSV")
    args = ap.parse_args()
    labels = json.loads(args.labels_ko.read_text(encoding="utf-8"))
    missing_labels: set[str] = set()

    def ko_label(table: dict, key: str) -> str:
        if key not in table:
            missing_labels.add(key)
            return key
        return table[key]

    def ko_d3(d3: str, d2: str = "") -> str:
        # 같은 영어 조각이 그룹마다 뜻이 다르다(체위 › Positions = 체위, BDSM › Locations = 장소) - 그룹별 덮어쓰기가 먼저.
        override = (labels.get("d3_override") or {}).get(f"{d2}|{d3}")
        if override:
            return override
        # 큰 절에서 올린 이름 `A · B` 는 하위 이름만 보인다 - 그룹 안에서 '헤어스타일 · ' '페티시 · ' 가 반복되면
        # 목록이 길어지고 읽기 어렵다(Gemini 교정 2026-10-14).
        return ko_label(labels["d3"], d3.split(" · ")[-1])

    def dropped(tag: str) -> bool:
        return bool(color_exclusion_reason(tag) or COSPLAY_RE.search(tag))

    tree = json.loads(args.tree.read_text(encoding="utf-8"))
    vocab = {n: (int(o), r, l) for n, o, r, l in PackReader(args.map).json_of("tags")}
    pages = tree["pages"]

    # ---- D1 <- D2 ------------------------------------------------------------------------
    d1_order = []
    page_d1: dict[str, str] = {}
    also_in: dict[str, list] = defaultdict(list)
    for sec in tree["root"]:
        if sec["part"] != "Visual characteristics":
            continue
        d1_order.append(sec["section"])
        for it in sec["items"]:
            t = it["target"]
            if t in page_d1:
                if page_d1[t] != sec["section"]:
                    also_in[t].append(sec["section"])
            else:
                page_d1[t] = sec["section"]
    changed = True
    while changed:  # 루트에 없고 그룹 쪽이 가리켜 따라 들어간 쪽 = 가리킨 쪽의 갈래
        changed = False
        for name, p in pages.items():
            for s in p.get("sections", []):
                for r in s["refs"]:
                    if r in pages and r not in page_d1 and name in page_d1:
                        page_d1[r] = page_d1[name]
                        changed = True
    page_order = {t: i for i, t in enumerate(page_d1)}

    # ---- D3 이름: 큰 절은 하위 제목을 올린다 ------------------------------------------------------
    promote: set[tuple[str, str]] = set()
    for pg, p in pages.items():
        size, subs = Counter(), defaultdict(set)
        for s in p.get("sections", []):
            if not s["path"]:
                continue
            size[s["path"][0]] += sum(1 for i in s["items"] if "map_obs" in i)
            if len(s["path"]) > 1:
                subs[s["path"][0]].add(s["path"][1])
        for head, n in size.items():
            if n > SPLIT_OVER and subs[head]:
                promote.add((pg, head))

    def d3_of(pg: str, path: list[str]) -> str:
        if not path:
            return INTRO
        if (pg, path[0]) in promote and len(path) > 1:
            return f"{path[0]} · {path[1]}"
        return path[0]

    # 쪽마다 D3 차례(위키 순서)
    d3_order: dict[str, list[str]] = defaultdict(list)
    for pg, p in pages.items():
        for s in p.get("sections", []):
            d = d3_of(pg, s["path"])
            if d not in d3_order[pg]:
                d3_order[pg].append(d)

    # ---- 잎 모으기 ------------------------------------------------------------------------------
    leaves: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)  # (d2, d3) -> tag -> leaf
    placed_by: dict[str, set] = defaultdict(set)

    def mapname(tag: str) -> str:
        """위키 이름(밑줄) -> 맵 어휘 이름. 맵은 공백을 쓰지만 `>_<` `^_^` 같은 이모티콘은 밑줄을 그대로 둔다
        - 무조건 공백으로 바꾸면 이모티콘이 전부 어휘에서 떨어진다(`^_^` 관측 10만)."""
        return tag if tag in vocab else space(tag)

    def usable(tag: str, lanes) -> bool:
        v = vocab.get(tag)
        return bool(v) and v[2] in lanes and not dropped(tag)

    def put(d2: str, d3: str, tag: str, via: str, parent: str | None = None, depth: int = 1):
        if (d2, d3) in leaves and tag in leaves[(d2, d3)]:
            return
        obs, _role, lane = vocab[tag]
        leaf = {"tag": tag, "obs": obs, "lane": lane, "via": via}
        if parent:
            leaf["parent"] = parent
        if depth > 1:
            leaf["depth"] = depth
        leaves[(d2, d3)][tag] = leaf
        placed_by[tag].add(via)

    for pg in page_d1:
        p = pages.get(pg) or {}
        for s in p.get("sections", []):
            d3 = d3_of(pg, s["path"])
            for it in s["items"]:
                tag = mapname(it["tag"])
                if usable(tag, LANES_DIRECT):
                    par = mapname(it["parent"]) if it.get("parent") else None
                    put(pg, d3, tag, "direct", par, it.get("depth", 1))

    # 쪽 첫머리(제목 없는 절)의 멤버. 자리 [쪽] 만 있을 때 '절 없음(첫머리)' 과 '절 모름(위키 참조)' 을 가른다
    # - `reflection` 은 theme 쪽 첫머리에 있는데 그 자식들이 `Related` 칸으로 갔다.
    intro_members = {pg: {it["tag"] for s in p.get("sections", []) if not s["path"] for it in s["items"]}
                     for pg, p in pages.items()}

    def at_to_slot(at: list[str], anchor: str | None = None) -> tuple[str, str] | None:
        pg = at[0]
        if pg not in page_d1:
            return None
        if len(at) > 1:
            return pg, d3_of(pg, at[1:])
        if anchor and anchor.replace(" ", "_") in intro_members.get(pg, ()):
            return pg, INTRO
        return pg, "Related"

    # 위키 본문 참조로 쪽만 아는 태그(`Related` 칸)는 Codex 가 절을 정해 준 대로 놓는다(사용자 결정 2026-10-14).
    related = {r["tag"]: r for r in read_tsv(args.related)} if args.related else {}
    related_count = Counter()
    related_flags: list[str] = []
    for tag, pl in tree["placements"].items():
        if pl["via"] == "none" or not usable(tag, {"general", "adult"}):
            continue
        if pl["via"] == "direct":
            # 위 쪽 순회가 이미 놓았다. 못 놓은 것은 맵 어휘가 **옛 이름**인 태그다
            # (`doughnut` <-> 위키 `donut`, `arm on shoulder` <-> `arm on another's shoulder`) - 새 이름의 자리에 놓는다.
            if tag not in placed_by:
                for at in pl["at"]:
                    slot = at_to_slot(at, mapname(pl["anchor"]))
                    if slot:
                        put(*slot, tag, "direct")
            continue
        if pl["via"] == "wiki_ref" and tag in related:
            r = related[tag]
            related_count[r["decision"]] += 1
            if r["decision"] == "place":
                put(r["d2"], r["d3"], tag, "wiki_ref")
            elif r["decision"] == "flag":
                related_flags.append(tag)
            continue
        anchor = mapname(pl["anchor"]) if pl.get("anchor") else None
        for at in pl["at"]:
            slot = at_to_slot(at, anchor if pl["via"] in ("implied", "children") else None)
            # 빌려 온 부모의 자리도 쪽만 알 때(`reflective water` -> reflection) 부모가 받은 절을 따른다.
            if slot and slot[1] == "Related" and anchor in related and related[anchor]["decision"] == "place":
                slot = (related[anchor]["d2"], related[anchor]["d3"])
            if slot:
                put(*slot, tag, pl["via"], anchor if pl["via"] == "implied" else None)

    # ---- Codex + 사용자 결정 ------------------------------------------------------------------
    codex = {r["tag"]: r for r in read_tsv(args.codex / "placements.tsv")}
    orph = {r["tag"]: r for r in read_tsv(args.codex / "orphans.tsv")}
    for r in read_tsv(args.decisions):
        codex[r["tag"]] = dict(r, method="user")

    obj_name = {}
    for d3, names in OBJECT_LISTS.items():
        for n in names.replace("\n", "").split("|"):
            if n.strip():
                obj_name[n.strip()] = d3

    def codex_slot(r: dict) -> tuple[str, str] | None:
        d2 = r["d2"]
        if r["decision"] == "new_section":
            key = (d2, r["new_d3"])
            if key in MOVE_TO_OBJECTS:
                return OBJ, MOVE_TO_OBJECTS[key]
            if key in MERGE_INTO_EXISTING:
                return d2, MERGE_INTO_EXISTING[key]
            return d2, r["new_d3"]
        path = [] if r["d3_path"] in ("", INTRO) else [x.strip() for x in r["d3_path"].split(">")]
        return d2, d3_of(d2, path)

    unplaced, excluded = [], Counter()
    excluded_tags: set[str] = set()
    for tag, r in codex.items():
        if not usable(tag, {"general", "adult"}):
            continue
        via = "user" if r.get("method") == "user" else "codex"
        if r["decision"] in ("place", "new_section"):
            put(*codex_slot(r), tag, via)
        elif r["decision"] == "exclude":
            excluded["codex_exclude"] += 1
            excluded_tags.add(tag)
        elif tag in obj_name:
            put(OBJ, obj_name[tag], tag, "objects")
        elif DO_NOT_USE_RE.match(orph.get(tag, {}).get("wiki_excerpt", "")):
            excluded["wiki_says_do_not_use"] += 1
            excluded_tags.add(tag)
        else:
            unplaced.append({"tag": tag, "obs": vocab[tag][0], "lane": vocab[tag][2]})
    for tag in related_flags:
        if tag not in placed_by:
            unplaced.append({"tag": tag, "obs": vocab[tag][0], "lane": vocab[tag][2], "from": "related_flag"})
    page_d1[OBJ] = "Objects"
    page_order[OBJ] = page_order.get("tag_group:sex_objects", len(page_order)) + 0.5
    for d3 in list(OBJECT_LISTS) + list(MOVE_TO_OBJECTS.values()):
        if d3 not in d3_order[OBJ]:
            d3_order[OBJ].append(d3)

    # ---- 정리(이벤트 맵 취지에 안 맞는 그룹 · 절) · 살리기 ---------------------------------------------
    prune_stats = Counter()
    pre_prune_slots = set(leaves)  # 살리기는 정리 전에 있던 자리면 된다(밈 춤 절을 지우고 거기에 셋만 되살린다)
    slot_dropped: set[str] = set()
    split_sources: set[tuple[str, str]] = set()  # 나눠서 비운 절 - 살리기가 여기를 가리키면 옛 절이 되살아난다

    def drop_by_regex(t: str) -> bool:  # 명세가 없으면 아무것도 안 뺀다
        return False
    if args.prune:
        spec = json.loads(args.prune.read_text(encoding="utf-8"))
        # 위키에 없는 새 그룹(사물 › 탈것 등). 정리 동작이 그리로 절을 옮기기 전에 만든다.
        for nd in (spec.get("new_d2") or {}).get("list", []):
            page_d1[nd["id"]] = nd["d1"]
            page_order[nd["id"]] = page_order.get(nd.get("after"), len(page_order)) + 0.5
        for item in spec["items"]:
            for op in item["ops"]:
                d2 = op["d2"]
                have = [k for k in leaves if k[0] == d2]
                if not have:
                    raise SystemExit(f"prune: 그룹이 없다 {item['id']} {d2}")
                for d in op.get("d3", []):
                    if (d2, d) not in leaves:
                        raise SystemExit(f"prune: 절이 없다 {item['id']} {d2} / {d}")
                if op["op"] == "drop_d2":
                    gone = have
                elif op["op"] == "drop_d3":
                    gone = [(d2, d) for d in op["d3"]]
                elif op["op"] == "keep_d3":
                    gone = [k for k in have if k[1] not in op["d3"]]
                elif op["op"] in ("merge_d2", "merge_d3"):
                    into = tuple(op["into"])
                    if into not in leaves:
                        raise SystemExit(f"prune: 합칠 절이 없다 {item['id']} {into}")
                    src = have if op["op"] == "merge_d2" else [(d2, d) for d in op["d3"]]
                    for k in src:
                        for tag, leaf in leaves[k].items():
                            leaves[into].setdefault(tag, dict(leaf, merged_from=d2))
                    gone = src
                elif op["op"] == "move_d3":
                    # 절을 통째로 다른 그룹으로(이름 그대로). 하늘 · 날씨를 장소로 모을 때 쓴다.
                    dst = op["into_d2"]
                    if dst not in page_d1:
                        raise SystemExit(f"prune: 옮길 그룹이 없다 {item['id']} {dst}")
                    rename = op.get("as") or {}  # 옮기며 절 이름을 바꾼다(탈것 그룹에 '기타' 가 셋 겹치지 않게)
                    for d in op["d3"]:
                        nd = rename.get(d, d)
                        for tag, leaf in leaves.pop((d2, d)).items():
                            leaves[(dst, nd)].setdefault(tag, dict(leaf, moved_from=d2))
                        if nd not in d3_order[dst]:
                            d3_order[dst].append(nd)
                    gone = []
                elif op["op"] == "reassign":
                    # 큰 절 나누기 · 태그 옮기기: [태그, 원래 그룹, 원래 절, 새 그룹, 새 절]. 새 절은 원래 절 바로 뒤에 선다.
                    for tag, sd2, sd3, dd2, dd3 in op["rows"]:
                        split_sources.add((sd2, sd3))
                        leaf = leaves.get((sd2, sd3), {}).pop(tag, None)
                        if leaf is None:
                            continue
                        if dd2 not in page_d1:
                            raise SystemExit(f"prune: 재배정 그룹이 없다 {item['id']} {dd2}")
                        leaves[(dd2, dd3)].setdefault(tag, dict(leaf, reassigned_from=f"{sd2}|{sd3}"))
                        order = d3_order[dd2]
                        if dd3 not in order:
                            order.insert(order.index(sd3) + 1 if (dd2 == sd2 and sd3 in order) else len(order), dd3)
                        prune_stats[item["id"]] += 1
                    for k in [k for k in leaves if not leaves[k]]:
                        del leaves[k]
                    gone = []
                elif op["op"] == "drop_tags_in":
                    # 그 절에서만 몇 개를 뺀다(탈것 › 기타의 군대 · 국가 이름처럼 절은 쓸 만하고 몇 개만 엉뚱할 때).
                    for d in op["d3"]:
                        for tag in op["tags"]:
                            if leaves[(d2, d)].pop(tag, None) is not None:
                                prune_stats[item["id"]] += 1
                    slot_dropped |= set(op["tags"])  # 다른 자리로 살리지 않으면 '버림' 이다
                    gone = []
                else:
                    raise SystemExit(f"prune: 모르는 op {op}")
                for k in gone:
                    prune_stats[item["id"]] += len(leaves.pop(k, {}))
                if op["op"] in ("drop_d2", "merge_d2"):
                    page_d1.pop(d2, None)
        for i, d2 in enumerate((spec.get("order_first") or {}).get("d2", [])):
            page_order[d2] = -100 + i  # 1단 안에서 맨 앞(장소를 찾기 쉽게 - 사용자)
        for d2, d1 in ((spec.get("move_d2_to_d1") or {}).get("map") or {}).items():
            if d2 not in page_d1 or d1 not in d1_order:
                raise SystemExit(f"prune: 1단 옮기기 대상이 없다 {d2} -> {d1}")
            page_d1[d2] = d1
        drop = spec.get("drop_tags") or {}
        drop_names = set(drop.get("tags", []))
        excluded_tags |= drop_names  # 지도에 자리가 없던 것을 버린 경우도 '버림' 으로 센다
        regexes = drop.get("regex") or []
        regexes = [regexes] if isinstance(regexes, str) else regexes
        drop_res = [re.compile(r) for r in regexes]
        keep_re = re.compile(drop["regex_except"]) if drop.get("regex_except") else None

        def drop_by_regex(t: str) -> bool:
            return any(r.match(t) for r in drop_res) and not (keep_re and keep_re.search(t))

        for k in list(leaves):
            for tag in [t for t in leaves[k] if t in drop_names or drop_by_regex(t)]:
                del leaves[k][tag]
                prune_stats["drop_tags"] += 1
                excluded_tags.add(tag)
    rescued = 0
    if args.rescue:
        for r in read_tsv(args.rescue):
            # 옮긴 절 · 새 절(이름표에 이름이 있으면 - 무기 › '총기' 처럼)도 된다
            slot_ok = ((r["d2"], r["d3"]) in pre_prune_slots or (r["d2"], r["d3"]) in leaves
                       or all(p in labels["d3"] for p in r["d3"].split(" · ")))
            if (r["d2"], r["d3"]) in split_sources and (r["d2"], r["d3"]) not in leaves:
                raise SystemExit(f"rescue: 나눠서 비운 절을 가리킨다(새 절로 옮겨라) {r['tag']} {r['d2']} / {r['d3']}")
            if not slot_ok or r["d2"] not in page_d1:
                raise SystemExit(f"rescue: 자리가 없다 {r['tag']} {r['d2']} / {r['d3']}")
            if r["tag"] in vocab:
                put(r["d2"], r["d3"], r["tag"], "rescue")
                rescued += 1
    # 자식 자리를 빌렸는데 그 자리가 맥락용 절인 태그는, 살리기로 제자리를 얻었으면 빌린 자리에서 뺀다
    # (`chair` 는 '~위에 › 물건 위에' 가 아니라 가구에 - 리뷰 2026-10-14).
    rescued_tags = {r["tag"] for r in read_tsv(args.rescue)} if args.rescue else set()
    for k in list(leaves):
        for tag in [t for t, leaf in leaves[k].items() if leaf["via"] == "children" and t in rescued_tags]:
            del leaves[k][tag]
    # 진짜 자리를 얻은 태그는 임시 `Related` 칸(쪽만 아는 자리)에서 뺀다.
    for k in [k for k in leaves if k[1] == "Related"]:
        for tag in [t for t in leaves[k] if any(t in v for kk, v in leaves.items() if kk != k and kk[1] != "Related")]:
            del leaves[k][tag]
        if not leaves[k]:
            del leaves[k]

    # ---- 조립 ---------------------------------------------------------------------------------
    out_d1 = []
    for d1 in d1_order:
        d2s = []
        for pg in sorted((p for p, d in page_d1.items() if d == d1), key=lambda p: page_order[p]):
            d3s = []
            names = d3_order.get(pg, []) + sorted({d for (p, d) in leaves if p == pg} - set(d3_order.get(pg, [])))
            for d3 in names:
                tags = list(leaves.get((pg, d3), {}).values())
                if tags:
                    d3s.append({"id": d3, "label_en": d3, "label_ko": ko_d3(d3, pg), "tags": tags})
            if d3s:
                label = OBJ if pg == OBJ else pg.split(":", 1)[-1].replace("_", " ")
                d2s.append({"id": pg, "label_en": "everyday objects" if pg == OBJ else label,
                            "label_ko": ko_label(labels["d2"], pg),
                            "also_in": also_in.get(pg, []), "d3": d3s})
        if d2s:
            out_d1.append({"id": d1, "label_en": d1, "label_ko": ko_label(labels["d1"], d1), "d2": d2s})

    # ---- 통계 ---------------------------------------------------------------------------------
    cand = {n for n, (o, r, l) in vocab.items() if l in ("general", "adult") and not dropped(n)}
    placed = {t for v in leaves.values() for t in v}  # 정리로 빠진 태그는 세지 않는다
    cand_obs = sum(vocab[n][0] for n in cand)
    d3_sizes = [len(d3["tags"]) for d1 in out_d1 for d2 in d1["d2"] for d3 in d2["d3"]]
    big = sorted(((len(d3["tags"]), d2["id"], d3["id"]) for d1 in out_d1 for d2 in d1["d2"] for d3 in d2["d3"]
                  if len(d3["tags"]) > SPLIT_OVER), reverse=True)
    homes = Counter(sum(1 for k in leaves if t in leaves[k]) for t in placed)
    stats = {
        "d1": len(out_d1),
        "d2": sum(len(d1["d2"]) for d1 in out_d1),
        "d3": len(d3_sizes),
        "leaf_slots": sum(d3_sizes),
        "unique_tags": len(placed),
        "unique_tags_by_lane": dict(Counter(vocab[t][2] for t in placed)),
        "map_candidates_general_adult": len(cand),
        "candidate_coverage_tags": round(len(cand & placed) / len(cand), 4),
        "candidate_coverage_obs": round(sum(vocab[n][0] for n in cand & placed) / cand_obs, 4),
        "d3_size": {"median": sorted(d3_sizes)[len(d3_sizes) // 2], "max": max(d3_sizes),
                    "le3": sum(1 for s in d3_sizes if s <= 3), "over_split": len(big)},
        "d3_over_split": [{"size": n, "d2": a, "d3": b} for n, a, b in big],
        "homes_per_tag": {str(k): v for k, v in sorted(homes.items())},
        "excluded": dict(excluded),
        "dropped_cosplay_vocab": sum(1 for n in vocab if COSPLAY_RE.search(n)),
        "related_applied": dict(related_count),
        "related_left_in_placeholder": sum(len(v) for (p, d), v in leaves.items() if d == "Related"),
        "missing_labels": sorted(missing_labels),
        "unplaced_count": len(unplaced),
        "unplaced_obs_share": round(sum(u["obs"] for u in unplaced) / cand_obs, 4),
        "via_unique": dict(Counter(min(placed_by[t], key=["user", "direct", "implied", "children", "wiki_ref",
                                                            "codex", "objects", "rescue"].index) for t in placed)),
        "pruned_slots_tags": dict(prune_stats),
        "pruned_lost_tags": len(set(placed_by) - placed),
        # 맵 후보인데 지도에도 · 미배치 목록에도 · 버린 것에도 없는 태그 = 조용히 사라진 것. 0 이어야 한다
        # (콜론 설명 링크를 고쳤을 때 탁자 · 거울 15개가 이렇게 사라졌다).
        "not_accounted": sorted(t for t in cand - placed - {u["tag"] for u in unplaced} - excluded_tags
                                - (set(placed_by) - placed) - slot_dropped if not drop_by_regex(t)),
        "rescued": rescued,
    }
    per_d1 = []
    for d1 in out_d1:
        tags = {t["tag"] for d2 in d1["d2"] for d3 in d2["d3"] for t in d3["tags"]}
        per_d1.append({"d1": d1["id"], "ko": d1["label_ko"], "d2": len(d1["d2"]),
                       "d3": sum(len(d2["d3"]) for d2 in d1["d2"]), "tags": len(tags),
                       "obs_share": round(sum(vocab[t][0] for t in tags & cand) / cand_obs, 4)})
    stats["per_d1"] = per_d1

    out = {
        "schema": "naia-event-map-3depth-draft-v1",
        "rules": {"split_over": SPLIT_OVER, "color": "dropped (core.event_map.policy.color_exclusion_reason)",
                  "cosplay": "dropped (`... (cosplay)` character tags)",
                  "lanes_direct": sorted(LANES_DIRECT), "lanes_inferred": ["adult", "general"]},
        "sources": {"tree": str(args.tree).replace("\\", "/"), "codex": str(args.codex).replace("\\", "/"),
                    "decisions": str(args.decisions).replace("\\", "/"), "map": str(args.map).replace("\\", "/")},
        "d1": out_d1,
        "unplaced": sorted(unplaced, key=lambda u: -u["obs"]),
        "stats": stats,
    }
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
