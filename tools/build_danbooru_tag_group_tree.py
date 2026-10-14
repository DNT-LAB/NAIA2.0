# -*- coding: utf-8 -*-
"""Danbooru 위키 `tag_groups` -> 이벤트 맵용 계층 트리(JSON).

사용법
    python tools/build_danbooru_tag_group_tree.py --wiki <위키 덤프 parquet> --out <트리 json>
        [--snapshot data/danbooru_tag_snapshot] [--map <event_map.naiamap>]

    예)
      python tools/build_danbooru_tag_group_tree.py ^
        --wiki data/danbooru_wiki_snapshot/tag_group_pages_20261014.json ^
        --out data/danbooru_wiki_snapshot/tag_group_tree.json ^
        --map C:\\VNR\\DEV\\NAIA-Event-Map-Build\\full-min5-20260912\\event_map.naiamap

원본
    `--wiki` 는 둘 중 하나다.
      .json    라이브 API 로 받은 쪽 묶음 `{"pages": [{title, body, updated_at, is_deleted}, ...]}`.
               2026-10-14 판 = `tag_group:*` 111쪽(삭제 표시 19) + 루트의 Visual 갈래가 가리키는 일반 쪽 22.
               ⚠️ 국내 망에서 danbooru.donmai.us 는 바로 붙으면 연결이 끊긴다 - **safebooru.donmai.us 를
               한 번 연 뒤** 같은 브라우저로 danbooru 로 가면 열린다(사용자 안내). curl 은 안 된다.
      .parquet HF 위키 덤프. `tag_group:*` 가 다 들어 있는 것은 `patvessel/danbooru-wiki-2606`
               (2026-06-01, 100쪽)뿐이다 - `dartags/danbooru-wiki-2609` 는 태그가 붙은 쪽만 담아 0쪽.

구조 (DText)
    `tag_groups` 쪽      h5 = 큰 갈래(Visual / Copyrights / Metatags), h6 = 갈래(Body · Attire ...),
                         글머리표 `*` `**` = 그룹과 하위 그룹.
    `tag_group:<x>` 쪽   h4/h5/h6 = 쪽 안의 절, 글머리표 깊이 = 태그 위계(`sitting` > `seiza`).
    한 줄에 링크가 여럿이면(`[[arm behind back]] / [[arms behind back]]`) 같은 깊이의 형제다.
    "See [[tag group:...]]" 처럼 다른 그룹을 가리키는 줄은 멤버가 아니라 참조(refs)로 둔다.

출력은 사람이 다시 손볼 원재료다 - 화면에 그대로 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.event_map.policy import color_exclusion_reason  # noqa: E402

LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]*))?\]\]")
HEAD_RE = re.compile(r"^h([1-6])(?:#[\w-]+)?\.\s*(.*)$", re.I)
BULLET_RE = re.compile(r"^(\*+)\s*(.*)$")
EXPAND_OPEN_RE = re.compile(r"^\[expand(?:=[^\]]*)?\]", re.I)
SEE_RE = re.compile(r"^\(?\s*(see|for )", re.I)
# 이 이름의 절은 다른 쪽으로 가는 길잡이다 - 멤버가 아니다.
# ⚠️ 그냥 "Related tags" 는 넣지 마라 - `mask` 같은 태그 위키는 그 절이 본 목록(종류 · 재질 ...)이다.
REF_HEAD_RE = re.compile(r"^(see also|related tag groups?|external links?|references?)\b", re.I)
GROUP_PREFIXES = ("tag_group:", "list_of_")
CRAWL_PARTS = {"Visual characteristics", "Metatags"}
TG_LINK_RE = re.compile(r"\[\[\s*(tag[ _]group:[^\]|]+)", re.I)


def norm_title(raw: str) -> str:
    """Danbooru 위키 제목 규칙: 앞뒤 공백 제거 · 소문자 · 공백은 밑줄."""
    t = raw.strip().lower()
    t = re.sub(r"\s+", "_", t)
    return t


def is_group_title(t: str) -> bool:
    return t == "tag_groups" or t.startswith(GROUP_PREFIXES)


def links_of(text: str) -> list[tuple[str, str]]:
    out = []
    for m in LINK_RE.finditer(text):
        target = m.group(1)
        if target.startswith("#"):
            continue
        out.append((norm_title(target), (m.group(2) or target).strip()))
    return out


def strip_expand(body: str) -> list[str]:
    """머리의 [expand=Table of Contents] 목차를 걷는다(링크가 아니라 앵커라 해롭진 않지만 줄이 섞인다)."""
    lines = body.replace("\r\n", "\n").split("\n")
    out, inside = [], False
    for ln in lines:
        s = ln.strip()
        if EXPAND_OPEN_RE.match(s):
            inside = True
            continue
        if inside:
            if s.lower().startswith("[/expand]"):
                inside = False
            continue
        out.append(ln)
    return out


def parse_root(body: str) -> list[dict]:
    """`tag_groups` 쪽 -> [{part, section, items:[{target, label, depth}]}]."""
    part = None
    sections: list[dict] = []
    cur = None
    for ln in strip_expand(body):
        s = ln.strip()
        h = HEAD_RE.match(s)
        if h:
            level, title = int(h.group(1)), h.group(2).strip()
            if level <= 5:
                part = title
                cur = {"part": part, "section": None, "items": []}
                sections.append(cur)
            else:
                cur = {"part": part, "section": title, "items": []}
                sections.append(cur)
            continue
        b = BULLET_RE.match(s)
        if b and cur is not None:
            depth = len(b.group(1))
            for target, label in links_of(b.group(2))[:1]:
                cur["items"].append({"target": target, "label": label, "depth": depth})
    return [x for x in sections if x["items"]]


def parse_page(body: str) -> dict:
    """그룹 쪽 하나 -> 절 목록. 절 = {path:[제목...], items:[{tag, depth, parent}], refs:[...]}"""
    heads: dict[int, str] = {}
    sections: list[dict] = []
    cur = {"path": [], "level": 0, "items": [], "refs": []}
    sections.append(cur)
    stack: list[str] = []  # 글머리표 깊이별 마지막 태그
    in_table = False
    for ln in strip_expand(body):
        s = ln.strip()
        if not s:
            continue
        h = HEAD_RE.match(s)
        if h:
            # 제목에 링크가 박힌 절이 있다("[[Smile]]", "[[Surprised]] / [[Scared]]") - 보이는 글자만 남긴다.
            title = LINK_RE.sub(lambda m: (m.group(2) or m.group(1)).strip(), h.group(2))
            level, title = int(h.group(1)), re.sub(r"\s+", " ", title).strip()
            for k in [k for k in heads if k >= level]:
                del heads[k]
            heads[level] = title
            cur = {"path": [heads[k] for k in sorted(heads)], "level": level, "items": [], "refs": []}
            sections.append(cur)
            stack = []
            continue
        low = s.lower()
        if low.startswith("[table"):
            in_table = True
        if low.startswith("[/table"):
            in_table = False
        b = BULLET_RE.match(s)
        if b:
            depth, text = len(b.group(1)), b.group(2)
        else:
            depth, text = (1 if in_table else 0), s
        # `[[lipstick tube]]: Used to apply [[lipstick]]` - 콜론 뒤는 설명이다. 설명 속 링크는 멤버가 아니다
        # (화장 그룹에 `table` 이 들어온 길). 콜론 앞까지만 본다.
        cut = text.find("]]:")
        if cut >= 0:
            text = text[: cut + 2]
        # `[[family bonding]] - Two or more [[family]] members ...` · `[[Raised inner eyebrows]], ... of [[smug]]ness`
        # - 대시 · 쉼표 뒤의 문장도 설명이다(theme 에 `family` `reflection` 이, eyebrows 에 `smug` 가 들어온 길).
        m = re.search(r"\]\]\s*(?:-|–|—)\s|\]\],\s+(?!\[\[)[a-z]", text)
        if m:
            text = text[: m.start() + 2]
        # `[[heart background]] ([[heart]])` - 괄호 속은 참조다. 이걸 멤버로 잡아 `weapon` `cloud` `food` 가
        # 배경 그룹에 들어갔고, 함의로 `gun` `rifle` `cloudy sky` 145개가 그 가짜 자리를 빌려 갔다.
        refs_in_paren = []
        if b:
            def _paren(m):
                refs_in_paren.extend(t for t, _ in links_of(m.group(0)))
                return " "
            text = re.sub(r"\((?:[^()]*?)\[\[[^()]*\)", _paren, text)
            cur["refs"].extend(refs_in_paren)
        found = links_of(text)
        if not found:
            continue
        see = (bool(SEE_RE.match(text)) or not b and not in_table
               or any(REF_HEAD_RE.match(x) for x in cur["path"]))
        if see:
            # 본문 문장 속 링크 · "See ..." 줄 = 멤버가 아니다.
            for target, label in found:
                cur["refs"].append(target)
            continue
        stack = stack[: max(depth - 1, 0)]
        parent = stack[-1] if stack else None
        first = None
        for target, label in found:
            if is_group_title(target):
                cur["refs"].append(target)
                continue
            cur["items"].append({"tag": target, "depth": depth, "parent": parent})
            if first is None:
                first = target
        if first is not None and depth >= 1:
            stack = stack[: depth - 1] + [first]
    return {"sections": [x for x in sections if x["items"] or x["refs"]]}


def load_alias(snapshot: Path) -> dict[str, str]:
    al = pd.read_parquet(snapshot / "tag_aliases.parquet")
    al = al[al["status"] == "active"]
    return dict(zip(al["antecedent_name"], al["consequent_name"]))


def load_tags(snapshot: Path) -> pd.DataFrame:
    t = pd.read_parquet(snapshot / "tags.parquet", columns=["name", "category", "post_count", "is_deprecated"])
    return t.set_index("name")


def load_map_vocab(path: Path | None) -> dict[str, tuple[int, str, str]]:
    if not path:
        return {}
    from core.event_map.pack import PackReader  # noqa: E402

    pk = PackReader(path)
    rows = pk.json_of("tags")
    return {name: (int(obs), role, lane) for name, obs, role, lane in rows}


def occurrences(pages: dict, tag: str) -> list[list[str]]:
    """태그가 멤버로 나오는 자리 [쪽, 절 제목...] 전부."""
    at = []
    for t, p in pages.items():
        for sec in p.get("sections", []):
            if any(it["tag"] == tag for it in sec["items"]):
                at.append([t] + sec["path"])
    return at


def place_map_vocab(vocab, pages, member_of, alias, snapshot: Path, wiki_full: Path | None,
                    sex_pages: set) -> dict:
    """맵 후보(general · adult 갈래) 태그마다 트리의 자리를 정한다. 순서대로 먼저 걸린 것:

    direct    그룹 쪽에 그대로 나온다
    implied   Danbooru 함의를 위로 타고 올라가 멤버에 닿는다(black skirt -> skirt)
    children  함의상 자식이 멤버다(braid <- single braid) - 그 자식의 자리를 빌린다
    wiki_ref  그 태그의 위키 본문이 어떤 tag_group 을 가리킨다(쪽만 알고 절은 모른다)
    none      손으로 채울 자리
    """
    if not vocab:
        return {}
    imp = pd.read_parquet(snapshot / "tag_implications.parquet")
    imp = imp[imp["status"] == "active"]
    up, down = defaultdict(list), defaultdict(list)
    for a, c in zip(imp["antecedent_name"], imp["consequent_name"]):
        up[a].append(c)
        down[c].append(a)
    wiki_body = {}
    if wiki_full:
        wk = pd.read_parquet(wiki_full, columns=["title", "body"])
        wiki_body = dict(zip(wk["title"], wk["body"]))
    occ_cache: dict[str, list] = {}

    def occ(tag):
        if tag not in occ_cache:
            occ_cache[tag] = occurrences(pages, tag)
        return occ_cache[tag]

    def inferred(tag, lane):
        """추론으로 빌린 자리. 일반 태그는 성행위 쪽 자리를 빌리지 않는다 -
        `tail` 이 sex_acts 에도 멤버라(tail insertion 의 부모) `horse tail` 이 거기로 끌려갔다."""
        at = occ(tag)
        if lane == "general":
            kept = [a for a in at if a[0] not in sex_pages]
            return kept
        return at

    out = {}
    for name, (obs, role, lane) in vocab.items():
        if lane not in ("general", "adult"):
            continue
        u = name.replace(" ", "_")
        u = alias.get(u, u)
        if u in member_of:
            out[name] = {"via": "direct", "anchor": u, "at": occ(u)}
            continue
        seen, q, hit = {u}, [u], None
        while q and hit is None:
            x = q.pop(0)
            for c in up.get(x, []):
                if c in member_of and inferred(c, lane):
                    hit = c
                    break
                if c not in seen:
                    seen.add(c)
                    q.append(c)
        if hit:
            out[name] = {"via": "implied", "anchor": hit, "at": inferred(hit, lane)}
            continue
        # 자식의 자리를 빌리는 것은 자식이 부모의 **한 종류**일 때만(`shoulder_bag` -> bag, `single_braid` -> braid
        # = 자식 이름이 부모 이름으로 끝난다). `on_chair` `holding_pillow` `horn_ornament` `cloud_focus` 처럼 부모를
        # 맥락으로 쓰는 파생 태그의 자리를 빌리면 `chair` 가 '~위에' 에, `horns` 가 장신구에 갔다(리뷰 2026-10-14).
        heads = {u, u[:-1]} if u.endswith("s") else {u}
        # `on_chair` `holding_pillow` 도 이름이 부모로 끝난다 - 전치사 · 동작 말로 시작하면 종류가 아니라 맥락이다.
        # `holding_pen` -> pen 은 들고 있는 것 그룹의 절(문구 · 공구 · 의료 기구 …)이 물건 분류로 쓸 만해서 허용한다.
        context_words = {"on", "in", "under", "over", "hugging", "carrying", "grabbing", "sitting", "lying",
                         "against", "behind", "from", "with", "without", "no", "into", "through", "between",
                         "beside", "above", "below", "near", "riding", "wearing", "adjusting", "removing", "unworn"}
        kids = sorted((a for a in down.get(u, []) if a in member_of and inferred(a, lane)
                       and any(a.endswith("_" + h) for h in heads) and a.split("_", 1)[0] not in context_words),
                      key=lambda a: -len(inferred(a, lane)))
        if kids:
            out[name] = {"via": "children", "anchor": kids[0], "at": inferred(kids[0], lane)}
            continue
        refs = [norm_title(g) for g in TG_LINK_RE.findall(wiki_body.get(u, ""))]
        refs = sorted({g for g in refs if g in pages and not pages[g].get("missing")})
        if refs:
            out[name] = {"via": "wiki_ref", "anchor": None, "at": [[g] for g in refs]}
            continue
        out[name] = {"via": "none", "anchor": None, "at": []}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--snapshot", type=Path, default=Path("data/danbooru_tag_snapshot"))
    ap.add_argument("--map", type=Path, default=None)
    ap.add_argument("--wiki-full", type=Path, default=None,
                    help="태그 위키 전체 덤프 parquet(dartags/danbooru-wiki-2609). 고아 태그의 본문이 가리키는 그룹을 찾는다")
    args = ap.parse_args()

    if args.wiki.suffix.lower() == ".json":
        live = json.loads(args.wiki.read_text(encoding="utf-8"))
        by_title = {p["title"]: (p["body"], p["updated_at"]) for p in live["pages"] if not p.get("is_deleted")}
    else:
        wiki = pd.read_parquet(args.wiki, columns=["title", "body", "updated_at", "is_deleted"])
        wiki = wiki[~wiki["is_deleted"]]
        by_title = {t: (b, u) for t, b, u in zip(wiki["title"], wiki["body"], wiki["updated_at"])}
    alias = load_alias(args.snapshot)
    tags = load_tags(args.snapshot)
    vocab = load_map_vocab(args.map)
    color_vocab = sorted(n for n in vocab if color_exclusion_reason(n))
    vocab = {n: v for n, v in vocab.items() if not color_exclusion_reason(n)}

    root_body, root_updated = by_title["tag_groups"]
    root = parse_root(root_body)

    # 루트가 가리키는 쪽(그룹 · list_of · 일반 태그 위키)을 전부 펼친다. 그룹 쪽 안의 다른 그룹 링크도 따라간다.
    # 작품 · 캐릭터 목록(Copyrights 갈래)은 맵과 무관해 받지도 펼치지도 않는다.
    pages: dict[str, dict] = {}
    queue = [it["target"] for sec in root if sec["part"] in CRAWL_PARTS for it in sec["items"]]
    seen = set()
    unlinked_done = False
    while queue or not unlinked_done:
        if not queue:
            # 루트에 아직 안 걸린 그룹 쪽(2026-10 판의 dress · glasses · smileys ...)도 담되 표시한다.
            unlinked_done = True
            queue = [t for t in by_title if t.startswith("tag_group:") and t not in seen]
            for t in queue:
                pages.setdefault(t, {})["_unlinked"] = True
            continue
        t = queue.pop(0)
        t = alias.get(t, t)
        if t in seen:
            continue
        seen.add(t)
        if t not in by_title:
            pages[t] = {"missing": True}
            continue
        body, upd = by_title[t]
        p = parse_page(body)
        p["updated_at"] = upd
        if pages.get(t, {}).get("_unlinked"):
            p["unlinked"] = True
        pages[t] = p
        if t.startswith("tag_group:"):
            for sec in p["sections"]:
                queue.extend(r for r in sec["refs"] if r.startswith("tag_group:"))

    # 멤버 태그를 별칭으로 맞추고 건수 · 맵 어휘를 붙인다.
    def resolve(tag: str) -> dict:
        canon = alias.get(tag, tag)
        info = {"tag": canon}
        if canon != tag:
            info["from"] = tag
        if canon in tags.index:
            r = tags.loc[canon]
            info["cat"] = int(r["category"])
            info["posts"] = int(r["post_count"])
            if int(r["is_deprecated"]):
                info["deprecated"] = True
        else:
            info["unknown"] = True
        v = vocab.get(canon.replace("_", " ")) or vocab.get(canon)
        if v:
            info["map_obs"], info["map_role"], info["map_lane"] = v
        return info

    # 색상 태그는 버린다(사용자 지정 2026-10-14). 맵이 후보에서 빼는 것과 **같은 함수**다.
    # 색 태그 아래 달린 태그는 그 색 태그의 부모를 부모로 잇는다.
    member_of: dict[str, set] = defaultdict(set)
    color_items: set[str] = set()
    for t, p in pages.items():
        for sec in p.get("sections", []):
            resolved = []
            lifted: dict[str, str | None] = {}
            for it in sec["items"]:
                canon = alias.get(it["tag"], it["tag"])
                parent = alias.get(it["parent"], it["parent"]) if it["parent"] else None
                while parent in lifted:
                    parent = lifted[parent]
                if color_exclusion_reason(canon):
                    lifted[canon] = parent
                    color_items.add(canon)
                    continue
                r = resolve(it["tag"])
                r["depth"] = it["depth"]
                if parent:
                    r["parent"] = parent
                resolved.append(r)
                member_of[r["tag"]].add(t)
            sec["items"] = resolved
            sec["refs"] = sorted(set(sec["refs"]))

    sex_pages = {alias.get(it["target"], it["target"]) for sec in root if sec["section"] == "Sex"
                 for it in sec["items"]}
    placements = place_map_vocab(vocab, pages, member_of, alias, args.snapshot, args.wiki_full, sex_pages)

    # ---- 통계 ------------------------------------------------------------------------------
    visual_parts = {"Visual characteristics"}
    visual_pages = set()
    for sec in root:
        if sec["part"] in visual_parts:
            for it in sec["items"]:
                visual_pages.add(alias.get(it["target"], it["target"]))
    # 그룹 쪽에서 따라 들어간 그룹도 visual 로 친다(루트 visual 에서 닿은 것).
    changed = True
    while changed:
        changed = False
        for t in list(visual_pages):
            for sec in pages.get(t, {}).get("sections", []):
                for r in sec["refs"]:
                    if r.startswith("tag_group:") and r in pages and r not in visual_pages:
                        visual_pages.add(r)
                        changed = True

    visual_tags = {tag for tag, ps in member_of.items() if ps & visual_pages}
    stats = {"pages": len(pages), "missing_pages": sorted(t for t, p in pages.items() if p.get("missing")),
             "visual_pages": len(visual_pages), "member_tags": len(member_of), "visual_member_tags": len(visual_tags),
             "color_dropped": {"member_tags": len(color_items), "map_vocab": len(color_vocab)}}
    if vocab:
        vis_names = {t.replace("_", " ") for t in visual_tags} | visual_tags
        lanes = Counter()
        lanes_hit = Counter()
        obs_all = Counter()
        obs_hit = Counter()
        for name, (obs, role, lane) in vocab.items():
            lane = lane or "none"
            lanes[lane] += 1
            obs_all[lane] += obs
            if name in vis_names:
                lanes_hit[lane] += 1
                obs_hit[lane] += obs
        stats["map_coverage"] = {
            lane: {"tags": lanes[lane], "in_visual_groups": lanes_hit[lane],
                   "tag_ratio": round(lanes_hit[lane] / lanes[lane], 4) if lanes[lane] else 0,
                   "obs_ratio": round(obs_hit[lane] / obs_all[lane], 4) if obs_all[lane] else 0}
            for lane in sorted(lanes)}
        # 맵 후보(general · adult) 중 관측이 큰데 어느 그룹에도 없는 태그 = 손으로 채울 자리.
        orphan = sorted(((obs, name, role, lane) for name, (obs, role, lane) in vocab.items()
                         if lane in ("general", "adult") and name not in vis_names
                         and name.replace(" ", "_") not in member_of),
                        reverse=True)
        stats["map_orphans_top"] = [{"tag": n, "obs": o, "role": r, "lane": l} for o, n, r, l in orphan[:300]]
        stats["map_orphans_count"] = len(orphan)
    if placements:
        via = Counter()
        via_obs = Counter()
        for name, pl in placements.items():
            via[pl["via"]] += 1
            via_obs[pl["via"]] += vocab[name][0]
        total = sum(via_obs.values()) or 1
        stats["placement_via"] = {k: {"tags": via[k], "obs_ratio": round(via_obs[k] / total, 4)}
                                  for k in ("direct", "implied", "children", "wiki_ref", "none")}
    multi = Counter(len(v & visual_pages) for k, v in member_of.items() if k in visual_tags)
    stats["visual_membership_histogram"] = {str(k): v for k, v in sorted(multi.items())}

    out = {
        "schema": "naia-danbooru-tag-group-tree-v1",
        "source": {"wiki": str(args.wiki).replace("\\", "/"), "root_updated_at": root_updated,
                   "snapshot": str(args.snapshot).replace("\\", "/"),
                   "map": str(args.map).replace("\\", "/") if args.map else None},
        "root": root,
        "pages": pages,
        "placements": placements,
        "stats": stats,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    brief = {k: v for k, v in stats.items() if k not in ("map_orphans_top",)}
    print(json.dumps(brief, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
