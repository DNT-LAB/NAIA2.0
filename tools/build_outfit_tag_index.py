"""의상 태그 의미 색인 - 태그 하나를 고르면 '다른 의상' 을 찾게 해 주는 관계표를 굽는다.

읽는 것(빌드 때만):
  data/outfit_presets.json                         세트 · 칸(tag_slot)
  tools/presets_data/outfit_vocab.json             kind_alias(miniskirt -> skirt 등)
  data/danbooru_tag_snapshot/tag_implications.parquet  함의(개발용 스냅숏 - 배포 안 함 → 결과만 굽는다)

쓰는 것: data/outfit_tag_index.json  (런타임은 core/outfit_tag_semantics.py 가 의상 팩과 함께 읽는다)

태그마다 담는 관계:
  broader   함의 부모(pleated skirt -> skirt) - 의상 어휘 안의 것만
  narrower  함의 자식 + 같은 종류의 꾸밈 판(skirt -> pleated skirt · miniskirt …)
  siblings  같은 종류(끝 낱말 = kind) · 같은 함의 부모를 둔 태그 - 같은 칸만
  group     물건 갈래 = Danbooru 함의의 맨 위 조상 중 의상 어휘의 garment(beret -> hat · hairclip -> hair ornament).
            없으면 [kind]. 장신구 칸(HEAD · NECK · ARMS)은 갈래가 다르면 대체가 아니다 - 모자 · 머리핀 · 안경은 같이 쓴다
  swaps     풀마다, 같은 칸에서 '나머지는 그대로 두고 이 태그만 바꾼' 세트 쌍에서 모은 대체 태그(점수 0~1)
  count     풀마다 이 태그를 쓴 세트 수

세트 id 는 의상 팩을 다시 구우면 바뀐다 → 색인은 세트 id 를 담지 않는다(세트 목록은 런타임이 팩에서 찾는다).
팩의 sha256 을 build.inputs 에 적어 두어, 팩만 바뀌고 색인을 안 구웠으면 런타임이 알 수 있게 한다.
"""

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "data" / "outfit_presets.json"
VOCAB = ROOT / "tools" / "presets_data" / "outfit_vocab.json"
IMPLICATIONS = ROOT / "data" / "danbooru_tag_snapshot" / "tag_implications.parquet"
OUT = ROOT / "data" / "outfit_tag_index.json"
SCHEMA = "naia.outfit_tag_index.v1"
SWAP_LIMIT = 12
POOLS = ("female", "male")
# 한 칸에 서로 다른 물건 갈래가 함께 놓이는 칸 - 여기서는 같은 갈래끼리만 바꿔 입기로 본다.
ACCESSORY_SLOTS = frozenset({"HEAD", "NECK", "ARMS"})
# 몸에 다는 장신구 갈래 - 어느 칸에 있든 옷과 바꿔 입는 것이 아니다(TOP 칸의 navel piercing 이 shirt 의 대체로 나왔다).
ADORNMENT_GROUPS = frozenset({"jewelry", "piercing"})


def swappable(tag: str, other: str, slot: dict, group: dict) -> bool:
    """같은 칸의 두 태그를 '바꿔 입기' 로 볼 수 있나. 장신구 칸 · 장신구 갈래는 같은 갈래끼리만."""
    if slot.get(tag) != slot.get(other):
        return False
    mine, theirs = set(group[tag]), set(group[other])
    if slot.get(tag) in ACCESSORY_SLOTS or (mine | theirs) & ADORNMENT_GROUPS:
        return bool(mine & theirs)
    return True
# 함의 조상은 다르지만 목에 매는 '타이류' 는 서로 바꿔 매는 것(넥타이 <-> 보타이 <-> 리본).
GROUP_ALIAS = {name: "neckwear" for name in (
    "necktie", "bowtie", "neck ribbon", "neckerchief", "ascot", "bolo tie", "cravat", "jabot",
)}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def kind_of(tag: str, alias: dict) -> str:
    """옷의 종류 = 끝 낱말. 'shorts under skirt' 는 스커트가 아니라 반바지다(under 앞 낱말)."""
    head = tag.split(" under ")[0] if " under " in tag else tag
    word = head.split(" ")[-1]
    return alias.get(word, word)


def on_parent(tag: str, parent: str) -> bool:
    """'hat bow' · 'hat flower' 는 모자에 다는 것이지 모자가 아니다(함의 부모가 앞 낱말)."""
    return tag.startswith(parent + " ")


def load_implication_edges(path: Path) -> dict[str, set[str]]:
    """active 함의 전부 - 자식 -> 직접 부모(밑줄은 공백으로)."""
    import pandas as pd

    frame = pd.read_parquet(path, columns=["antecedent_name", "consequent_name", "status"])
    frame = frame[frame.status == "active"]
    edges = defaultdict(set)
    for child, parent in zip(frame.antecedent_name, frame.consequent_name):
        child, parent = child.replace("_", " "), parent.replace("_", " ")
        if child != parent:
            edges[child].add(parent)
    return edges


def item_groups(tags: set[str], edges: dict[str, set[str]], garments: set[str]) -> dict[str, list[str]]:
    """태그마다 맨 위 조상 중 garment 인 것(무늬 · 장식 같은 속성 조상은 버린다)."""
    out = {}
    for tag in tags:
        seen, stack, roots = set(), [tag], set()
        while stack:
            node = stack.pop()
            parents = edges.get(node, ())
            if not parents and node != tag:
                roots.add(node)
            for parent in parents:
                if parent not in seen:
                    seen.add(parent)
                    stack.append(parent)
        roots &= garments
        if roots:
            out[tag] = sorted(roots)
    return out


def load_implications(path: Path, tags: set[str], edges: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    """의상 어휘 안의 함의만 - 자식 -> 부모 집합(이행 폐포)."""
    edges = load_implication_edges(path) if edges is None else edges
    direct = defaultdict(set)
    for child, parents in edges.items():
        if child not in tags:
            continue
        direct[child].update(p for p in parents if p in tags)
    closure = {}
    for tag in tags:
        seen, stack = set(), [tag]
        while stack:
            for parent in direct.get(stack.pop(), ()):
                if parent not in seen and parent != tag:
                    seen.add(parent)
                    stack.append(parent)
        if seen:
            closure[tag] = seen
    return closure


def swap_scores(sets: list[list[str]], slot: dict, group: dict | None = None) -> dict[str, Counter]:
    """세트 쌍 (S, S') 에서 S 의 T 가 S' 의 U 로 바뀌고 나머지가 거의 같으면 T -> U 대체로 센다.

    '거의 같다' = S-{T} 에서 빠진 것 ≤ 1 · S' 에 U 말고 더 붙은 것 ≤ 1 · 겹침 ≥ 1. U 는 T 와 같은 칸.
    점수 = 겹침 / 합집합 크기의 합. 같은 쌍을 양쪽에서 세므로 대칭이다.
    """
    by_tag = defaultdict(list)
    for index, tags in enumerate(sets):
        for tag in tags:
            by_tag[tag].append(index)
    scores = defaultdict(Counter)
    for tag in sorted(by_tag):
        for index in by_tag[tag]:
            rest = set(sets[index]) - {tag}
            if not rest:
                continue
            overlap = Counter()
            for other_tag in rest:
                for other in by_tag[other_tag]:
                    overlap[other] += 1
            for other, shared in overlap.items():
                other_tags = set(sets[other])
                if tag in other_tags:
                    continue
                added = [u for u in other_tags - rest if slot.get(u) == slot.get(tag)]
                if len(added) != 1:
                    continue
                if group is not None and not swappable(tag, added[0], slot, group):
                    continue
                if len(rest - other_tags) > 1 or len(other_tags - rest - set(added)) > 1:
                    continue
                scores[tag][added[0]] += shared / len(rest | other_tags)
    return scores


def build(pack_path: Path = PACK, vocab_path: Path = VOCAB, implications_path: Path = IMPLICATIONS,
          *, edges: dict[str, set[str]] | None = None) -> dict:
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
    alias = vocab.get("kind_alias", {})
    garments = {name for name, row in vocab["tags"].items() if row.get("class") == "garment"}
    slot = pack["tag_slot"]
    tags = set(slot)
    if edges is None:
        edges = load_implication_edges(implications_path)
    implications = load_implications(implications_path, tags, edges)
    roots = item_groups(tags, edges, garments)
    def group_of(tag: str) -> list[str]:
        if tag in GROUP_ALIAS:  # neck ribbon 의 조상은 ribbon 이지만 매는 자리로는 타이류다
            return [GROUP_ALIAS[tag]]
        return sorted({GROUP_ALIAS.get(g, g) for g in roots.get(tag) or [kind_of(tag, alias)]})

    group = {tag: group_of(tag) for tag in tags}

    counts = {pool: Counter() for pool in POOLS}
    pool_sets = {pool: [] for pool in POOLS}
    for row in pack["sets"]:
        pool_sets[row["pool"]].append(list(row["tags"]))
        counts[row["pool"]].update(row["tags"])
    used = {tag for pool in POOLS for tag in counts[pool]}
    swaps = {pool: swap_scores(pool_sets[pool], slot, group) for pool in POOLS}

    children = defaultdict(set)
    for child, parents in implications.items():
        for parent in parents:
            children[parent].add(child)
    by_kind = defaultdict(set)
    for tag in used:
        by_kind[(kind_of(tag, alias), slot[tag])].add(tag)

    def total(tag: str) -> int:
        return counts["female"][tag] + counts["male"][tag]

    def ordered(group: set[str], tag: str) -> list[str]:
        # 같은 풀 둘의 대체 점수 합 → 세트 수 → 이름. 결정적이어야 한다(반복 빌드 바이트 같음).
        def key(other):
            swap = swaps["female"][tag].get(other, 0.0) + swaps["male"][tag].get(other, 0.0)
            return (-round(swap, 9), -total(other), other)
        return sorted(group, key=key)

    entries = {}
    for tag in sorted(used):
        kind = kind_of(tag, alias)
        broader = {p for p in implications.get(tag, ()) if p in used}
        narrower = {c for c in children.get(tag, ()) if c in used}
        if tag == kind:  # 맨 종류 이름(skirt)이면 같은 종류의 꾸밈 판 전부가 아래
            narrower |= {t for t in by_kind[(kind, slot[tag])] if t != tag}
        siblings = {t for t in by_kind[(kind, slot[tag])] if t != tag}
        for parent in broader:
            if on_parent(tag, parent):  # hat bow 의 형제는 모자들이 아니다
                continue
            siblings |= {c for c in children.get(parent, ())
                         if c in used and slot.get(c) == slot[tag] and not on_parent(c, parent)}
        siblings -= {tag} | broader | narrower
        entry = {
            "slot": slot[tag],
            "kind": kind,
            "group": group[tag],
            "count": {pool: counts[pool][tag] for pool in POOLS if counts[pool][tag]},
            "broader": ordered(broader, tag),
            "narrower": ordered(narrower, tag),
            "siblings": ordered(siblings, tag),
            "swaps": {},
        }
        for pool in POOLS:
            row = swaps[pool].get(tag)
            if not row:
                continue
            top = max(row.values())
            best = sorted(row.items(), key=lambda kv: (-round(kv[1], 9), kv[0]))[:SWAP_LIMIT]
            entry["swaps"][pool] = [[other, round(score / top, 3)] for other, score in best]
        entries[tag] = entry

    return {
        "schema": SCHEMA,
        "note": "의상 태그 의미 색인 - tools/build_outfit_tag_index.py 가 굽는다. 손으로 고치지 말 것",
        "build": {
            "builder": "build_outfit_tag_index.py",
            "built_at": datetime.now(timezone.utc).isoformat(),
            "inputs": {"outfit_presets": {"name": pack_path.name, "sha256": _sha256(pack_path)}},
            "counts": {
                "tags": len(entries),
                "with_swaps": {pool: sum(1 for e in entries.values() if pool in e["swaps"]) for pool in POOLS},
                "with_family": sum(1 for e in entries.values() if e["broader"] or e["narrower"] or e["siblings"]),
            },
        },
        # 런타임이 '그 자리만 바꾼 의상' 을 찾을 때 같은 규칙을 쓴다.
        "rules": {"accessory_slots": sorted(ACCESSORY_SLOTS), "adornment_groups": sorted(ADORNMENT_GROUPS)},
        "tags": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", type=Path, default=PACK)
    parser.add_argument("--vocab", type=Path, default=VOCAB)
    parser.add_argument("--implications", type=Path, default=IMPLICATIONS)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    document = build(args.pack, args.vocab, args.implications)
    text = json.dumps(document, ensure_ascii=False, sort_keys=False, separators=(",", ":"))
    args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    counts = document["build"]["counts"]
    print(f"wrote {args.out} tags={counts['tags']} swaps={counts['with_swaps']} family={counts['with_family']} "
          f"bytes={len(text.encode('utf-8'))}")


if __name__ == "__main__":
    sys.exit(main())
